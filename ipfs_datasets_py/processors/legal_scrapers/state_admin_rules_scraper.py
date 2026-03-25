"""State administrative-rules scraper orchestration.

This module reuses the state-laws scraping pipeline, then keeps only
administrative-rule records so the output corpus is focused on state
administrative rules/codes.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from collections import defaultdict
from html import unescape
import io
import json
import logging
import math
import os
import re
import time
import warnings
import zipfile
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, quote, unquote, urldefrag, urlencode, urljoin, urlparse, urlunparse
import xml.etree.ElementTree as ET

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
from .state_laws_scraper import (
    US_STATES,
    _get_official_state_url,
    list_state_jurisdictions,
    scrape_state_laws,
)

logger = logging.getLogger(__name__)

_BLOCKING_FETCH_EXECUTOR = ThreadPoolExecutor(max_workers=8)
_STATE_WORKER_EXECUTOR = ThreadPoolExecutor(max_workers=4)
_UTAH_RULE_DETAIL_METADATA_CACHE: Dict[str, Dict[str, Any]] = {}


async def _run_blocking_fetch(fetch_callable: Any, request: Any) -> Any:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_BLOCKING_FETCH_EXECUTOR, lambda: fetch_callable(request))


async def _run_state_worker(worker_callable: Any) -> Any:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_STATE_WORKER_EXECUTOR, worker_callable)

US_50_STATE_CODES: List[str] = [code for code in US_STATES.keys() if code != "DC"]

_ADMIN_RULE_TEXT_RE = re.compile(
    r"administrative|admin\.?\s+code|code\s+of\s+regulations|regulation|agency\s+rule|oar\b|aac\b|arc\b|nmac\b",
    re.IGNORECASE,
)

_ADMIN_LINK_HINT_RE = re.compile(
    r"administrative|admin\.?\s+code|regulation|rules?|code|statute|chapter|subchapter|part|article|section|title|agency|board|commission|"
    r"state_agencies/[\w.-]+\.html|§\s*\d+|\b[A-Za-z]{2,4}(?:-[A-Za-z]{1,3})?\s*\d{3}\b|\b\d{2}:\d{2}\b|\b\d{1,3}\.\d{1,3}(?:\.\d{1,4})?\b",
    re.IGNORECASE,
)

_PORTAL_REFERENCE_RE = re.compile(
    r"portal\s+reference|landing\s+page|source\s+url:\s*https?://|entrypoint|seed\s+url",
    re.IGNORECASE,
)

_LEGAL_CONTENT_SIGNAL_RE = re.compile(
    r"\b(section|chapter|title|part|subchapter|authority|effective|amended|adopted|pursuant|rule|regulation|code)\b|§",
    re.IGNORECASE,
)

_NON_ADMIN_CODE_NAME_RE = re.compile(
    r"\b(general\s+laws|revised\s+statutes|compiled\s+laws|codified\s+laws|session\s+laws|constitution)\b",
    re.IGNORECASE,
)

_NON_ADMIN_SOURCE_URL_RE = re.compile(
    r"/statutes?(?:/|$)|/api/statutes?(?:/|$)|/rsa/html/|/constitution(?:/|$)|/ucc/(?:|index\.shtml)$|statutes\.capitol\.texas\.gov/|law\.justia\.com/codes/|"
    r"(?:^|https?://)(?:www\.)?sos\.arkansas\.gov/business-commercial-services-bcs/(?:|$)|"
    r"(?:^|https?://)(?:www\.)?sos\.arkansas\.gov/business-commercial-services-bcs/uniform-commercial-code-ucc/(?:|$)|"
    r"(?:^|https?://)(?:www\.)?sos\.arkansas\.gov/business-commercial-services-bcs/notary-e-notary(?:/|$)|"
    r"(?:^|https?://)(?:www\.)?sos\.arkansas\.gov/academics/(?:|$)|"
    r"(?:^|https?://)(?:www\.)?sos\.arkansas\.gov/search/results(?:/|$)|"
    r"(?:^|https?://)(?:www\.)?sos\.arkansas\.gov/uploads/Proposed_Rule_Cover_Sheet\.pdf(?:[#?]|$)|"
    r"(?:^|https?://)(?:[^/]+\.)?justia\.com/|(?:^|https?://)(?:www\.)?web\.archive\.org/web/\d+/https?://(?:[^/]+\.)?justia\.com/|"
    r"(?:^|https?://)(?:www\.)?uscode\.house\.gov/|(?:^|https?://)(?:www\.)?ecfr\.gov/|"
    r"(?:^|https?://)(?:www\.)?coloradosos\.gov/pubs/elections/Initiatives/titleBoard/(?:|$)|"
    r"(?:^|https?://)(?:www\.)?coloradosos\.gov/pubs/newsRoom/(?:|$)|"
    r"(?:^|https?://)(?:www\.)?coloradosos\.gov/pubs/rule_making/written_comments/(?:|$)|"
    r"(?:^|https?://)(?:www\.)?sos\.state\.co\.us/CCR/auth/loginHome\.do(?:\?|$)|"
    r"(?:^|https?://)(?:www\.)?ark\.org/arec_renewals(?:/|$)|"
    r"(?:^|https?://)(?:www\.)?ark\.org/sos/corpfilings(?:/|$)|"
    r"(?:^|https?://)(?:www\.)?azdirect\.az\.gov/(?:|$)|"
    r"(?:^|https?://)(?:www\.)?apps\.azlibrary\.gov/(?:|$)|"
    r"(?:^|https?://)(?:www\.)?extension\.arizona\.edu/(?:|$)|"
    r"(?:^|https?://)(?:www\.)?azed\.gov/sites/default/files/(?:|$)|"
    r"(?:^|https?://)(?:www\.)?sos\.arkansas\.gov/elections(?:/|$)|"
    r"(?:^|https?://)(?:www\.)?sos\.arkansas\.gov/\+ELECTIONS(?:|$)|"
    r"(?:^|https?://)(?:www\.)?le\.utah\.gov/|(?:^|https?://)(?:www\.)?legislature\.vermont\.gov/|(?:^|https?://)(?:www\.)?leg\.mt\.gov/|"
    r"(?:^|https?://)(?:www\.)?iga\.in\.gov/static-documents/(?:|$)|"
    r"(?:^|https?://)(?:www\.)?azleg\.gov/arsDetail(?:\?|/|$)|"
    r"(?:^|https?://)(?:www\.)?azleg\.gov/viewdocument(?:/viewDocument)?/\?docName=https?://(?:www\.)?azleg\.gov/ars/|"
    r"(?:^|https?://)(?:www\.)?azsos\.gov/business/notary-public(?:/|$)|"
    r"(?:^|https?://)(?:www\.)?azsos\.gov/block/rules-faq(?:[#?]|/|$)|"
    r"(?:^|https?://)(?:www\.)?sos\.alabama\.gov/administrative-services/(?:|$)|"
    r"(?:^|https?://)(?:www\.)?alisondb\.legislature\.state\.al\.us/alison/CodeOfAlabama/1975/|"
    r"(?:^|https?://)(?:www\.)?web\.archive\.org/web/\d+/https?://(?:www\.)?alisondb\.legislature\.state\.al\.us/alison/CodeOfAlabama/1975/|"
    r"(?:^|https?://)(?:www\.)?web\.archive\.org/web/\d+/http:/alisondb\.legislature\.state\.al\.us/alison/CodeOfAlabama/1975/|"
    r"(?:^|https?://)admincode\.legislature\.state\.al\.us/agency(?:/|$)|"
    r"(?:^|https?://)(?:www\.)?sdlegislature\.gov/Statutes(?:\?|/|$)|"
    r"(?:^|https?://)(?:www\.)?(?:malegislature\.gov|legislature\.ma\.gov)/Laws/GeneralLaws(?:/|$)|"
    r"(?:^|https?://)(?:www\.)?legislature\.mi\.gov/(?:$|rules(?:\?|/|$)|Search/ExecuteSearch|Laws/(?:MCL|ChapterIndex)(?:\?|/|$))|"
    r"(?:^|https?://)(?:www\.)?legislature\.mi\.gov/Laws/Index\?(?:[^#]*&)?ObjectName=mcl-chap|(?:^|https?://)(?:www\.)?texashuntingforum\.com/|"
    r"(?:^|https?://)(?:www\.)?rules\.sos\.ga\.gov/(?:help\.aspx|download_pdf\.aspx)|"
    r"(?:^|https?://)(?:www\.)?boardsandcommissions\.sd\.gov/",
    re.IGNORECASE,
)

_BAD_DISCOVERY_DOMAIN_RE = re.compile(
    r"(^|\.)(city-data\.com|legalclarity\.org|texashuntingforum\.com|montanaheritagecommission\.mt\.gov|wikipedia\.org|britannica\.com|ballotpedia\.org|zhihu\.com|pemfprofessionals\.com|superuser\.com|sportsbookreview\.com|sur\.ly|workspace\.google\.com|support\.google\.com|azcu\.edu|arkvalleyvoice\.com|faithiu\.edu)$",
    re.IGNORECASE,
)

_BAD_DISCOVERY_TEXT_RE = re.compile(
    r"site\s+has\s+moved|redirected\s+shortly|page\s+not\s+found|404\s+not\s+found|403\s+forbidden|toggle\s+navigation|submit\s+your\s+own\s+pictures|"
    r"the\s+request\s+could\s+not\s+be\s+satisfied|generated\s+by\s+cloudfront|request\s+blocked|"
    r"city-data\.com\s+does\s+not\s+guarantee|forum\s+cities\s+schools\s+neighborhoods|"
    r"administrative\s+rules\s+source\s+url:\s*https?://|you\s+need\s+to\s+enable\s+javascript\s+to\s+run\s+this\s+app|"
    r"javascript\s+is\s+not\s+enabled|there\s+are\s+currently\s+no\s+rules\s+pending\s+for\s+this\s+agency|"
    r"click\s+on\s+comment\s+deadline\s+date\s+to\s+submit\s+your\s+comment|public\s+hearing\s+dates|interim\s+committee\s+hearing|"
    r"forgot\s+password\??|request\s+account|email\s*\*\s*password\s*\*|from\s+wikipedia,\s+the\s+free\s+encyclopedia|"
    r"this\s+article\s+is\s+about\s+the\s+u\.s\.\s+state|u\.s\.\s+state\s*$|jump\s+to\s+content",
    re.IGNORECASE,
)

_NAVIGATION_PAGE_TOKEN_RE = re.compile(
    r"skip\s+to\s+(main\s+content|content)|site\s+map|contact\s+us|website\s+survey|"
    r"privacy\s+policy|quick\s+links|search\s+for\s+this:|menu|my\s+tlo|who\s+represents\s+me|"
    r"current\s+issue|media\s*\||help\s*\||faq\s*\||contact\s*\|",
    re.IGNORECASE,
)

_LANDING_PAGE_PHRASE_RE = re.compile(
    r"welcome\s+to\s+the\s+texas\s+administrative\s+code|view\s+the\s+current\s+texas\s+administrative\s+code|"
    r"search\s+the\s+texas\s+administrative\s+code|about\s+the\s+uniform\s+commercial\s+code|"
    r"in-person\s+services\s+for\s+the\s+office\s+of\s+the\s+texas\s+secretary\s+of\s+state\s+have\s+moved|"
    r"all\s+current\s+proposed\s+rules|rules\s+are\s+archived\s+20\s+days\s+after\s+filed\s+with\s+secretary\s+of\s+state|"
    r"browse\s+rules\s+and\s+regulations\s+of\s+the\s+state\s+of\s+georgia",
    re.IGNORECASE,
)

_OFF_TOPIC_HISTORY_PAGE_RE = re.compile(
    r"magazine\s+of\s+(?:western\s+)?history|on\s+the\s+cover|reviewed\s+by|vol\.\s*\d+\s*,\s*no\.\s*\d+|"
    r"membership\s+visit\s+about|event\s+spaces?\s+rental|montana\s+heritage\s+center|montana\s+heritage\s+commission|staff\s+directory",
    re.IGNORECASE,
)

_NON_RULE_ADMIN_LANDING_RE = re.compile(
    r"board\s+members|meeting\s+information|agenda\s+packet|public\s+comment|events\s+calendar|"
    r"past\s+meetings\s+and\s+minutes|board\s+training|member\s+directory|"
    r"subscribe\s+to\s+receive\s+.*email\s+updates|board\s+of\s+public\s+education|board\s+of\s+housing",
    re.IGNORECASE,
)

_GENERIC_ADMIN_INDEX_TITLE_RE = re.compile(
    r"^(administrative\s+rules|policies|home|rulemaking\s+resources)$",
    re.IGNORECASE,
)

_KS_PORTAL_CHROME_RE = re.compile(
    r"an\s+official\s+state\s+of\s+kansas\s+government\s+website|"
    r"kansas\s+secretary\s+of\s+state|business\s+services\s+division|"
    r"elections\s+division|publications\s+division|online\s+administrative\s+regulations|"
    r"proposed\s+regulations\s+open\s+for\s+comment|future\s+effective\s+regulations|"
    r"administrative\s+regulations\s+agency\s+resources|regulation\s+modernization\s+initiative",
    re.IGNORECASE,
)

_KS_RESOURCE_TOOLS_TEXT_RE = re.compile(
    r"permanent\s+regulation\s+tools|temporary\s+regulation\s+tools|"
    r"revocation\s+by\s+notice\s+tools|policy\s+and\s+procedure\s+manual|"
    r"secretary\s+of\s+state\s+permanent\s+regulation\s+filing\s+checklist|"
    r"other\s+useful\s+links",
    re.IGNORECASE,
)

_KS_RULE_LISTING_ROW_RE = re.compile(r"\b\d{1,2}-\d{1,2}-\d+[A-Za-z-]*\.\s", re.IGNORECASE)

_MI_RULEMAKING_TRANSACTION_TEXT_RE = re.compile(
    r"request\s+for\s+rulemaking|draft\s+rule\s+language|regulatory\s+impact\s+statement|"
    r"joint\s+committee\s+on\s+administrative\s+rules\s+package|"
    r"transaction\s+id=\d+|approved\s+on:",
    re.IGNORECASE,
)

_MI_ELAWS_INDEX_TEXT_RE = re.compile(
    r"search\s+this\s+site\s+by\s+google|michigan\s+administrative\s+code|michigan\s+register|"
    r"go\s+to\s+page|copyright\s+©\s+\d{4}\s+by\s+elaws|department\s+[A-Z]{1,4}\s+.+division",
    re.IGNORECASE,
)

_TN_SOS_SERVICE_PAGE_TEXT_RE = re.compile(
    r"current\s+filings|search\s+past\s+rule\s+filings|search\s+past\s+rulemaking\s+hearing\s+notices|"
    r"related\s+services|related\s+links|administrative\s+register\s+archive|"
    r"effective\s+rules\s+and\s+regulations\s+of\s+the\s+state\s+of\s+tennessee|"
    r"secretary\s+of\s+state\s+tre\s+hargett|uniform\s+administrative\s+procedures\s+act",
    re.IGNORECASE,
)

_NON_RULE_POLICY_PAGE_RE = re.compile(
    r"department\s+of\s+corrections\s+policies|policies\s+manual|contracts\s+policies\s+procedures|"
    r"social\s+media\s+terms\s+of\s+use|state\s+hr\s+policies|policy\s+and\s+procedure\s+management|"
    r"publication\s+contract|request\s+for\s+proposals?|notice\s+of\s+intent\s+to\s+award\s+contract|"
    r"sourcing\s+event\s+\d+",
    re.IGNORECASE,
)

_SEO_MIRROR_PAGE_RE = re.compile(
    r"website\s+value\s+calculator\s*&\s*seo\s+checker|domain\s+authority|estimated\s+worth:?|"
    r"is\s+.+\s+down\s+for\s+everyone\s+or\s+just\s+me\?|offseo\.com|check\s+whois|"
    r"google\s+trends|seo\s+report|remove\s+website|source\s+analysis|location\s+analysis",
    re.IGNORECASE,
)

_FORUM_PAGE_RE = re.compile(
    r"rules?\s+of\s+conduct|forum\s+guidelines|family\s+friendly|volunteer\s+moderators?|"
    r"moderation\s+is\s+interpretation|posting\s+privilege|signature\s+images|back\s+to\s+the\s+.*forum|"
    r"do\s+not\s+create\s+more\s+than\s+one\s+user\s+account|classifieds",
    re.IGNORECASE,
)

_CA_OAL_CCR_LANDING_TEXT_RE = re.compile(
    r"barclays,\s+a\s+division\s+of\s+thomson-reuters|documents\s+in\s+sequence|pop-up blocker/westlaw|"
    r"quick\s+links|recent\s+actions\s+taken\s+by\s+oal\s+on\s+regulations",
    re.IGNORECASE,
)

_CA_WESTLAW_TOC_TEXT_RE = re.compile(
    r"skip\s+to\s+navigation|skip\s+to\s+main\s+content|home\s+updates\s+search\s+help|"
    r"privacy\s+accessibility\s+california\s+office\s+of\s+administrative\s+law",
    re.IGNORECASE,
)

_CA_WESTLAW_DOCUMENT_BOILERPLATE_LINE_RE = re.compile(
    r"^(?:\d+\s+CA\s+ADC\s+§\s*[\w.-]+|Barclays\b.*)$",
    re.IGNORECASE,
)

_CA_WESTLAW_DOCUMENT_BREADCRUMB_LINE_RE = re.compile(
    r"^(?:Title\s+\d+\.|Division\s+\d+(?:\.\d+)?\.|Chapter\s+\d+(?:\.\d+)?\.|Article\s+(?:\d+|[IVXLCM]+)\.)(?:\s+.*)?$",
    re.IGNORECASE,
)

_INDIANA_IARP_FOOTER_LINE_RE = re.compile(
    r"^(?:Administrative\s+Drafting\s+Manual|Historical\s+List\s+of\s+Executive\s+Orders|"
    r"Submissions\s+to\s+Attorney\s+General's\s+Office|General\s+Assembly|Agency\s+List|"
    r"LSA\s+Rulemaking\s+Templates|Contact/About\s+Us|Site\s+Map)$",
    re.IGNORECASE,
)

_INDIANA_IARP_TOOLBAR_LINE_RE = re.compile(
    r"^(?:PDF|Copy\s+Article|Article\s+\d+(?:\.\d+)?|Rule\s+\d+\.?|Current)$",
    re.IGNORECASE,
)

_INDIANA_IARP_BODY_LINE_RE = re.compile(
    r"^(?:\d+\s+IAC\s+[\w.-]+(?:\s+.+)?|Authority:\s*.+|Affected:\s*.+|Sec\.\s*\d+\.)$",
    re.IGNORECASE,
)

_AZ_RULEMAKING_META_TEXT_RE = re.compile(
    r"title\s+1\.\s+rules\s+and\s+the\s+rulemaking\s+process|"
    r"secretary of state\s*[\-\u2013]?\s*rules and rulemaking",
    re.IGNORECASE,
)

_AZ_ADMIN_REGISTER_TEXT_RE = re.compile(
    r"arizona\s+administrative\s+register|issue\s+date\s+pages\s+authenticated\s+pdf|"
    r"publishing\s+information|rules\s+and\s+your\s+rights",
    re.IGNORECASE,
)

_AZSOS_RULES_PORTAL_NAV_TEXT_RE = re.compile(
    r"visit\s+openbooks|ombudsman\s+citizens\s+aide|register\s+to\s+vote|save\s+with\s+azrx",
    re.IGNORECASE,
)

_AZ_RULES_PORTAL_CHROME_RE = re.compile(
    r"tracking\s+pixel\s+disclaimer|visit\s+openbooks|save\s+with\s+azrx|"
    r"subscriber\s+info\s+subscribe|arizona\s+administrative\s+code\s+on\s+amp|"
    r"subscribe\s+to\s+our\s+code\s+update\s+email\s+service|main\s+navigation",
    re.IGNORECASE,
)

_AR_SOS_PORTAL_TEXT_RE = re.compile(
    r"search\s+arkansas\s+administrative\s+rules|code\s+of\s+arkansas\s+rules|"
    r"state\s+agency\s+public\s+meeting\s+calendar|agency\s+rule\s+filing\s+instructions|"
    r"bulk\s+data\s+download|arkansas\s+secretary\s+of\s+state",
    re.IGNORECASE,
)

_GA_GAC_DEPARTMENT_PATH_RE = re.compile(r"^/gac/\d+/?$", re.IGNORECASE)
_GA_GAC_CHAPTER_PATH_RE = re.compile(r"^/gac/\d+-\d+/?$", re.IGNORECASE)
_GA_GAC_SUBJECT_PATH_RE = re.compile(r"^/gac/\d+(?:-\d+){2,}/?$", re.IGNORECASE)
_GA_GAC_RULE_PATH_RE = re.compile(r"^/gac/\d+(?:-\d+){2,}-\.\d+[A-Za-z0-9-]*/?$", re.IGNORECASE)
_GA_GAC_DEPARTMENT_ROW_RE = re.compile(r"\bDepartment\s+\d+\.\s", re.IGNORECASE)
_GA_GAC_SUBJECT_ROW_RE = re.compile(r"\bSubject\s+\d+(?:-\d+){2,}\.\s", re.IGNORECASE)
_GA_GAC_RULE_ROW_RE = re.compile(r"\bRule\s+\d+(?:-\d+){2,}-\.\d+[A-Za-z0-9-]*\b", re.IGNORECASE)

_CT_EREGS_ROOT_PATH_RE = re.compile(r"^/eRegsPortal/Browse/RCSA/?$", re.IGNORECASE)
_CT_EREGS_TITLE_PATH_RE = re.compile(r"^/eRegsPortal/Browse/RCSA/Title_[0-9A-Za-z]+/?$", re.IGNORECASE)
_CT_EREGS_SUBTITLE_PATH_RE = re.compile(
    r"^/eRegsPortal/Browse/RCSA/Title_[0-9A-Za-z]+Subtitle_[^/]+/?$",
    re.IGNORECASE,
)
_CT_EREGS_SECTION_PATH_RE = re.compile(
    r"^/eRegsPortal/Browse/RCSA/Title_[0-9A-Za-z]+Subtitle_[^/]+Section_[^/]+/?$",
    re.IGNORECASE,
)
_CT_EREGS_TITLE_ROW_RE = re.compile(r"\bTitle\s+\d+[a-z]?\s+-\s+[A-Z]", re.IGNORECASE)
_CT_EREGS_SUBTITLE_ROW_RE = re.compile(
    r"\b\d+[a-z]?(?:-\d+[a-z]?)+(?:\s+to\s+\d+[a-z]?(?:-\d+[a-z]?)+)?\s+-\s+[A-Z]",
    re.IGNORECASE,
)
_CT_EREGS_SECTION_ROW_RE = re.compile(r"\b(?:Sec\.\s*)?\d+[a-z]?(?:-\d+[a-z]?)+\b", re.IGNORECASE)

_CO_CCR_WELCOME_PATH_RE = re.compile(r"^/CCR/Welcome\.do/?$", re.IGNORECASE)
_CO_CCR_DEPT_LIST_PATH_RE = re.compile(r"^/CCR/NumericalDeptList\.do/?$", re.IGNORECASE)
_CO_CCR_AGENCY_LIST_PATH_RE = re.compile(r"^/CCR/NumericalAgencyList\.do/?$", re.IGNORECASE)
_CO_CCR_DOC_LIST_PATH_RE = re.compile(r"^/CCR/NumericalCCRDocList\.do/?$", re.IGNORECASE)
_CO_CCR_DISPLAY_RULE_PATH_RE = re.compile(r"^/CCR/DisplayRule\.do/?$", re.IGNORECASE)
_CO_CCR_GENERATE_RULE_PDF_PATH_RE = re.compile(r"^/CCR/GenerateRulePdf\.do/?$", re.IGNORECASE)
_CO_CCR_PDF_PATH_RE = re.compile(r"^/CCR/.+\.pdf$", re.IGNORECASE)
_CO_CCR_RULE_ROW_RE = re.compile(r"\b\d+\s+CCR\s+\d+(?:-\d+)+\b", re.IGNORECASE)
_CO_CCR_OPEN_RULE_WINDOW_RE = re.compile(
    r"OpenRuleWindow\('(?P<rule_version_id>\d+)'\s*,\s*'(?P<file_name>[^']+)'\s*\)",
    re.IGNORECASE,
)

_AK_AAC_TITLE_PATH_RE = re.compile(r"^/aac/\d+/?$", re.IGNORECASE)
_AK_AAC_CHAPTER_PATH_RE = re.compile(r"^/aac/\d+\.\d+/?$", re.IGNORECASE)
_AK_AAC_SECTION_PATH_RE = re.compile(r"^/aac/\d+(?:\.\d+){2,3}/?$", re.IGNORECASE)
_AK_BOOKVIEW_PATH_RE = re.compile(r"^/bookview/(?:\d+(?:\.\d+)*)/?$", re.IGNORECASE)
_AK_AAC_TITLE_ROW_RE = re.compile(r"\bTitle\s+\d+\.\s", re.IGNORECASE)
_AK_AAC_CHAPTER_ROW_RE = re.compile(r"\bChapter\s+\d+\.\d+\.\s", re.IGNORECASE)
_AK_AAC_SECTION_ROW_RE = re.compile(r"\bSection\s+\d+(?:\.\d+){2,3}\.\s", re.IGNORECASE)

_NM_NMAC_TITLES_PATH_RE = re.compile(r"^/nmac-home/nmac-titles/?$", re.IGNORECASE)
_NM_NMAC_TITLE_PATH_RE = re.compile(r"^/nmac-home/nmac-titles/title-\d+(?:-[a-z0-9]+)+/?$", re.IGNORECASE)
_NM_NMAC_CHAPTER_PATH_RE = re.compile(
    r"^/nmac-home/nmac-titles/title-\d+(?:-[a-z0-9]+)+/chapter-\d+(?:-[a-z0-9]+)+/?$",
    re.IGNORECASE,
)
_NM_NMAC_TITLE_ROW_RE = re.compile(r"\bTitle\s+0?\d+\s+[\u2013-]\s+[A-Z]", re.IGNORECASE)
_NM_NMAC_CHAPTER_ROW_RE = re.compile(r"\bChapter\s+\d+(?:[\u2013-]\d+)?\b", re.IGNORECASE)
_NM_NMAC_RULE_ROW_RE = re.compile(r"\b\d{1,2}\.\d{1,3}\.\d{1,3}\s+NMAC\b", re.IGNORECASE)
_NM_NMAC_PORTAL_TEXT_RE = re.compile(
    r"skip\s+to\s+content|related\s+pages|expand\s+list|powered\s+by\s+real\s+time\s+solutions|"
    r"state\s+records\s+center\s+&\s+archives|new\s+mexico\s+administrative\s+code",
    re.IGNORECASE,
)

_VT_NON_RULE_PORTAL_PATH_RE = re.compile(
    r"/SOS/rules/?$|/SOS/rules/(?:index\.php|search\.php|rssFeed\.php|calendar\.php|subscribe\.php|contact\.php|iCalendar\.php)$|"
    r"/secretary-of-state-services/apa-rules(?:/.*)?$",
    re.IGNORECASE,
)

_VT_PROPOSAL_POSTING_TEXT_RE = re.compile(
    r"proposed\s+rules\s+postings|deadline\s+for\s+public\s+comment|posting\s+date:|"
    r"hearing\s+information|rulemaking\s+contact\s+information|proposed\s+state\s+rules|"
    r"subscribe\s+to\s+rule\s+notices|upcoming\s+events",
    re.IGNORECASE,
)
_VT_RULE_DETAIL_TEXT_RE = re.compile(
    r"\brule\s+details\b|\brule\s+number\s*:|\bagency\s*:|\blegal\s+authority\s*:",
    re.IGNORECASE,
)

_VT_LEXIS_TOC_PATH_RE = re.compile(r"^/hottopics/codeofvtrules/?$", re.IGNORECASE)
_VT_LEXIS_DOC_PATH_RE = re.compile(
    r"^/shared/document/administrative-codes/urn:contentItem:[A-Za-z0-9:-]+$",
    re.IGNORECASE,
)
_VT_LEXIS_SHELL_TEXT_RE = re.compile(
    r"captcha\s+validation|robot\s+validation|we\s+use\s+captcha\s+on\s+this\s+site|"
    r"sign\s+in\s*\|\s*lexisnexis|sign\s+in\s+to\s+continue",
    re.IGNORECASE,
)
_VT_LEXIS_TOC_TEXT_RE = re.compile(
    r"code\s+of\s+vermont\s+rules|table\s+of\s+contents|agency\s+\d+\.\s+[A-Z]",
    re.IGNORECASE,
)

_RAW_HTML_TEXT_RE = re.compile(
    r"^\s*(?:<!DOCTYPE\s+html\b|<html\b|<head\b|<body\b)|<script\b|<meta\b|<noscript\b|</html>",
    re.IGNORECASE,
)

_WY_NON_RULE_PORTAL_TEXT_RE = re.compile(
    r"administrative\s+rules\s+search|advanced\s+search|results\s*\(\s*0\s*\)|no\s+results\s+found|"
    r"repository\s+for\s+rules\s+and\s+regulations|wyoming\s+secretary\s+of\s+state|"
    r"current\s+rules\s+proposed\s+rules\s+emergency\s+rules|quicklinks|state\s+login",
    re.IGNORECASE,
)

_UT_NON_RULE_PORTAL_PATH_RE = re.compile(
    r"^/(?:$|public/home/?|publications/?|about(?:/.*)?|contact(?:-us)?/?|help(?:/.*)?|category/public-news/?|"
    r"rulewriting-manual/?|administrative-rules-dashboard/?|researching(?:/.*)?|"
    r"publications/subscriptions/?|publications/executive-documents(?:/.*)?|subscriptions/?|"
    r"services/?|agency-listing/?|agency-resources/?)$",
    re.IGNORECASE,
)

_UT_NON_RULE_TITLE_RE = re.compile(
    r"^(?:About|Contact|Privacy|Services|Public News|Rulewriting Manual|eRules Help|"
    r"Rulemaking Help: Fiscal Analysis|Administrative Rules Dashboard|Subscriptions|"
    r"Finding the Right Agency to Contact|Researching Other Law|Executive Documents .*|"
    r"Utah Administrative Code Changes for GovOps)\b",
    re.IGNORECASE,
)

_UT_BULLETIN_NEWS_TITLE_RE = re.compile(
    r"issue\s+of\s+the\s+utah\s+state\s+bulletin\s+is\s+now\s+available|^publications\s*\|",
    re.IGNORECASE,
)

_UT_NON_RULE_NEWS_PATH_RE = re.compile(
    r"^/(?:rulesnews|category/[^/]+|changes-to-utah-administrative-code-links(?:-\d+)?)/?$",
    re.IGNORECASE,
)

_UT_NON_RULE_NEWS_TEXT_RE = re.compile(
    r"office\s+of\s+administrative\s+rules\s+news|"
    r"to\s+get\s+notified\s+via\s+email\s+on\s+new\s+versions\s+of\s+the\s+utah\s+state\s+bulletin|"
    r"changes\s+to\s+utah\s+administrative\s+code\s+links",
    re.IGNORECASE,
)

_UT_RULE_DETAIL_PATH_RE = re.compile(
    r"^/(?:public/rule/[^/]+/Current(?:%20|\+)Rules|api/public/getHTML/[^?#]+)",
    re.IGNORECASE,
)

_UT_NON_SUBSTANTIVE_INDEX_PATH_RE = re.compile(
    r"^(?:/?|/public/search(?:/.*)?|/utah-administrative-code/?|/category/publications/?|/publications/(?:administrative-rules-register|code-updates)/?)$",
    re.IGNORECASE,
)

_UT_BULLETIN_PDF_PATH_RE = re.compile(r"^/wp-content/uploads/b\d{8}\.pdf$", re.IGNORECASE)

_AZ_OFFICIAL_DOCUMENT_PATH_RE = re.compile(r"^/public_services/Title_\d{2}/\d+-\d+\.(?:pdf|rtf)$", re.IGNORECASE)

_TX_NON_SUBSTANTIVE_PORTAL_QUERY_RE = re.compile(
    r"(?:^|[?&])interface=(?:VIEW_TAC|SEARCH_TAC)(?:[&#]|$)",
    re.IGNORECASE,
)

_TX_TRANSFER_PATH_RE = re.compile(r"^/texreg/transfers(?:/|$)", re.IGNORECASE)
_TX_TRANSFER_NOTICE_TEXT_RE = re.compile(
    r"\brule\s+transfer\b|administratively\s+transferring|will\s+be\s+transferred\s+from\s+title\b|"
    r"conversion\s+chart|transfer\s+charts?\b",
    re.IGNORECASE,
)
_OK_NON_SUBSTANTIVE_LEGISLATURE_PATH_RE = re.compile(
    r"^/(?:regulations|administrative-code|code-of-regulations|rules|agency-rules|policies|departments)?/?$",
    re.IGNORECASE,
)
_OK_LLSDC_TEXT_RE = re.compile(
    r"law\s+librarians'?\s+society\s+of\s+washington|legislative\s+source\s+book|"
    r"state\s+legislatures,?\s+state\s+laws,?\s+and\s+state\s+regulations",
    re.IGNORECASE,
)
_OK_RULES_PORTAL_SHELL_TEXT_RE = re.compile(
    r"oklahoma\s+administrative\s+code.*administrative\s+code\s+search.*"
    r"title\s+1\.\s*executive\s+orders",
    re.IGNORECASE | re.DOTALL,
)
_OK_RULE_SECTION_NUM_RE = re.compile(r"^\d{1,3}:\d+(?:-\d+)+(?:\.\d+)?$")

_LOW_VALUE_LINK_TEXT_RE = re.compile(
    r"^(?:home|about(?:\s+us)?|contact(?:\s+us)?|help|privacy|services|state\s+login|login|myiar|subscriptions?)$",
    re.IGNORECASE,
)

_LOW_VALUE_LINK_URL_RE = re.compile(
    r"(?:#(?:home|about|contact)\b|/(?:about(?:/|$)|contact(?:-us)?(?:/|$)|help(?:/|$)|privacy(?:/|$)|services(?:/|$)|myiar(?:/|$)|"
    r"category/public-news(?:/|$)|publications/subscriptions(?:/|$)|state/my%20work/))",
    re.IGNORECASE,
)

_LIVE_FETCH_PREFERRED_HOSTS = {
    "iar.iga.in.gov",
    "eregulations.ct.gov",
    "rules.sos.ga.gov",
    "www.coloradosos.gov",
    "www.sos.state.co.us",
}

_TX_TRANSFER_INDEX_PATH_RE = re.compile(r"^/texreg/transfers(?:/|/index\.shtml)?$", re.IGNORECASE)

_MI_NON_RULE_PORTAL_PATH_RE = re.compile(r"^/(?:|home/?|admincode/admincode/?)$", re.IGNORECASE)

_RI_NON_RULE_PORTAL_PATH_RE = re.compile(r"^/organizations/?$", re.IGNORECASE)
_RI_RICR_DETAIL_PATH_RE = re.compile(r"^/regulations/part/[\w.-]+/?$", re.IGNORECASE)

_AZ_NON_RULE_LEGISLATURE_PATH_RE = re.compile(
    r"^/(?:regulations|administrative-code|code-of-regulations)/?$",
    re.IGNORECASE,
)

_AZLEG_NON_ADMIN_SEED_PATH_RE = re.compile(
    r"^/(?:|rules|regulations|administrative-code|code-of-regulations|agency-rules|policies|departments|bbapc/background/rules-bba)/?$",
    re.IGNORECASE,
)

_CA_NON_RULE_LEGISLATURE_PATH_RE = re.compile(
    r"^/(?:|rules|regulations|administrative-code|code-of-regulations|agency-rules|policies|faces/(?:codes|codes_displaytext|codedisplayexpand|codes_displayexpandedbranch)\.xhtml)/?$",
    re.IGNORECASE,
)

_IN_NON_RULE_LEGISLATURE_PATH_RE = re.compile(
    r"^/(?:regulations|administrative-code|code-of-regulations)/?$",
    re.IGNORECASE,
)

_MA_CMR_INVENTORY_PATH_RE = re.compile(
    r"^/(?:guides/code-of-massachusetts-regulations-cmr-by-number|"
    r"info-details/code-of-massachusetts-regulations-[a-z0-9-]+|"
    r"law-library/\d{1,3}[a-z]?-cmr)/?$",
    re.IGNORECASE,
)

_MA_CMR_DETAIL_PATH_RE = re.compile(r"^/regulations/[A-Za-z0-9-]+/?$", re.IGNORECASE)

_MA_GENERAL_LAWS_PATH_RE = re.compile(r"^/Laws/GeneralLaws(?:/.*)?$", re.IGNORECASE)

_MD_COMAR_INVENTORY_PATH_RE = re.compile(
    r"^/us/md/exec/comar(?:/[0-9]{2}[A-Z]?(?:\.[0-9]{2}[A-Z]?)?)?/?$",
    re.IGNORECASE,
)

_MD_COMAR_DETAIL_PATH_RE = re.compile(
    r"^/us/md/exec/comar/[0-9]{2}[A-Z]?(?:\.[0-9A-Z]{2,4}){2,}/?$",
    re.IGNORECASE,
)

_ME_RULES_INDEX_PATH_RE = re.compile(
    r"^/sos/rulemaking/agency-rules(?:/[a-z0-9-]+)?/?$",
    re.IGNORECASE,
)

_ME_RULE_DOCUMENT_PATH_RE = re.compile(
    r"^/sos/sites/maine\.gov\.sos/files/(?:inline-files|content/assets)/[^?#]+\.(?:docx|pdf)$",
    re.IGNORECASE,
)

_ME_RULE_DEPARTMENT_PATH_RE = re.compile(
    r"^/sos/rulemaking/agency-rules/[a-z0-9-]+/?$",
    re.IGNORECASE,
)

_MN_RULE_INDEX_PATH_RE = re.compile(
    r"^/rules(?:/numerical)?/?$",
    re.IGNORECASE,
)

_MN_RULE_AGENCY_PATH_RE = re.compile(
    r"^/rules/agency/\d+/?$",
    re.IGNORECASE,
)

_MN_RULE_DETAIL_PATH_RE = re.compile(
    r"^/rules/\d{4}/?$",
    re.IGNORECASE,
)

_MO_CSR_INDEX_PATH_RE = re.compile(
    r"^/adrules/csr/csr/?$",
    re.IGNORECASE,
)

_MO_CSR_TITLE_PATH_RE = re.compile(
    r"^/adrules/csr/current/\d+csr/\d+csr/?$",
    re.IGNORECASE,
)

_MO_CSR_PDF_PATH_RE = re.compile(
    r"^/cmsimages/adrules/csr/current/\d+csr/[^?#]+\.pdf$",
    re.IGNORECASE,
)

_NE_RULE_BROWSE_PATH_RE = re.compile(
    r"^/(?:browse-rules|rules)/?$",
    re.IGNORECASE,
)

_NE_RULE_FILESTORAGE_PDF_PATH_RE = re.compile(
    r"^/api/fileStorage/GetAsByteArray/(?:chapter-pdfs|title-pdfs)/[^?#]+\.pdf$",
    re.IGNORECASE,
)

_NE_RULES_API_BASE_URL = "https://rules.nebraska.gov/api"

_MT_COLLECTION_PATH_RE = re.compile(
    r"^/browse/collections/(?P<collection>[0-9a-fA-F-]+)/?$",
    re.IGNORECASE,
)
_MT_SECTION_PATH_RE = re.compile(
    r"^/browse/collections/(?P<collection>[0-9a-fA-F-]+)/sections/(?P<section>[0-9a-fA-F-]+)/?$",
    re.IGNORECASE,
)
_MT_POLICY_PATH_RE = re.compile(
    r"^/browse/collections/(?P<collection>[0-9a-fA-F-]+)/policies/(?P<policy>[0-9a-fA-F-]+)/?$",
    re.IGNORECASE,
)
_MT_PUBLIC_API_BASE_URL = "https://rules.mt.gov/api/policy-library-public"

_AL_PUBLIC_CODE_PATH_RE = re.compile(r"^/administrative-code/?$", re.IGNORECASE)
_AL_RULE_NUMBER_RE = re.compile(r"^\d{1,3}-[A-Z]-\d+(?:-\.\d+)+$", re.IGNORECASE)
_AL_PUBLIC_CODE_GRAPHQL_URL = "https://admincode.legislature.state.al.us/api/graphql"
_AL_PUBLIC_CODE_HASH = "b72bac93737153227218ba9055454a07afe68f2d"
_AL_AGENCY_SORT_TITLES_HASH = "97eb45e3d6371acfc256baecb90e51f2074a00c5"

_INDIANA_ADMIN_CODE_ARTICLE_PATH_RE = re.compile(
    r"^/code/(?P<edition>current|\d{4})/(?P<title_num>\d+)/(?P<article_num>\d+(?:\.\d+)*)/?$",
    re.IGNORECASE,
)
_INDIANA_ADMIN_CODE_API_BASE_URL = "https://drxya2s1hkmtl.cloudfront.net/api"
_INDIANA_NONCURRENT_ARTICLE_RE = re.compile(r"\((?:expired|repealed|transferred)\)", re.IGNORECASE)

_SD_RULE_INDEX_PATH_RE = re.compile(r"^/Rules/Administrative/?$", re.IGNORECASE)
_SD_RULE_DETAIL_PATH_RE = re.compile(r"^/Rules/Administrative/(?P<rule>\d{2}:\d{2}(?::\d{2}){0,3})/?$", re.IGNORECASE)
_SD_RULE_REFERENCE_RE = re.compile(r"^\d{2}:\d{2}(?::\d{2}){0,3}$")
_SD_DISPLAY_RULE_PATH_RE = re.compile(r"(?:^|/)DisplayRule\.aspx$", re.IGNORECASE)


def _prefers_live_fetch(url: str) -> bool:
    parsed = urlparse(str(url or "").strip())
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    if host == "advance.lexis.com" and _VT_LEXIS_DOC_PATH_RE.fullmatch(parsed.path or ""):
        return False
    if host in _LIVE_FETCH_PREFERRED_HOSTS:
        return True
    if host == "texas-sos.appianportalsgov.com" and path == "/rules-and-meetings":
        interface = str((parse_qs(parsed.query or "").get("interface") or [""])[0]).strip().upper()
        if interface in {"VIEW_TAC", "VIEW_TAC_SUMMARY"}:
            return True
    if host == "rules.ok.gov" and path == "/code":
        if str((parse_qs(parsed.query or "").get("titleNum") or [""])[0]).strip():
            return True
    if host in {"lexisnexis.com", "www.lexisnexis.com"} and _VT_LEXIS_TOC_PATH_RE.fullmatch(parsed.path or ""):
        return True
    if host == "advance.lexis.com" and path == "/container":
        return True
    if host == "sharetngov.tnsosfiles.com" and path in {
        "/sos/rules/index.htm",
        "/sos/rules/rules2.htm",
        "/sos/rules/rules_list.shtml",
        "/sos/rules/effectives/effectives.htm",
        "/sos/rules/tenncare.htm",
        "/sos/pub/tar/index.htm",
    }:
        return True
    if host == "adminrules.utah.gov" and (
        path.startswith("/public/search") or bool(_UT_RULE_DETAIL_PATH_RE.search(parsed.path or ""))
    ):
        return True
    if host == "rules.nebraska.gov" and (path == "/" or bool(_NE_RULE_BROWSE_PATH_RE.fullmatch(parsed.path or ""))):
        return True
    return False

_NH_ARCHIVED_RULE_CHAPTER_URL_RE = re.compile(
    r"^https?://web\.archive\.org/web/\d+/https?://(?:gc\.nh\.gov|(?:www\.)?gencourt\.state\.nh\.us)/rules/state_agencies/[\w.-]+\.html$",
    re.IGNORECASE,
)

_NH_ARCHIVED_RULE_CHAPTER_TEXT_RE = re.compile(
    r"\bchapter\s+[A-Za-z-]+\s*\d{3}\b|\bpart\s+[A-Za-z-]+\s*\d{3}\b|statutory\s+authority:|\bsource\.\b",
    re.IGNORECASE,
)

_NH_ARCHIVED_RULE_PREFIX_RE = re.compile(r"\b[A-Za-z]{2,4}(?:-[A-Za-z]{1,3})?\s*\d{3}\b")

_NH_RULES_PORTAL_TEXT_RE = re.compile(
    r"office\s+of\s+legislative\s+services|rulemaking\s+search|jlcar\s+meeting\s+dates|"
    r"rules\s+by\s+agency|administrative\s+rules\s+office|effective\s+adopted\s+rules\s+as\s+filed|"
    r"emergency\s+rules\s+currently\s+in\s+effect|quick\s+links|the\s+general\s+court\s+of\s+new\s+hampshire",
    re.IGNORECASE,
)

_NH_CHECKRULE_GUIDE_TEXT_RE = re.compile(
    r"how\s+to\s+double-check\s+the\s+online\s+rule|checking\s+for\s+later\s+filings\s+not\s+yet\s+online|"
    r"checking\s+for\s+expiration|official\s+version\s+of\s+a\s+rule|"
    r"administrative\s+rules\s+office\s+can\s+provide\s+information\s+about\s+rules",
    re.IGNORECASE,
)

_RULE_BODY_SIGNAL_RE = re.compile(
    r"§\s*\d|\barm\s+\d|\b\d{1,3}\.\d{1,3}\.\d{1,4}\b|authority\s*:|history\s*:|implementing\s*:|"
    r"purpose\s+of\s+regulations|notice\s+of\s+adoption|notice\s+of\s+proposed\s+(?:amendment|adoption|repeal)",
    re.IGNORECASE,
)

_OFFICIAL_RULE_INDEX_URL_RE = re.compile(
    r"(?:^|https?://)(?:rules\.mt\.gov/browse/collections(?:/|$)|sdlegislature\.gov/Rules/Administrative(?:/|$)|"
    r"rules\.nebraska\.gov(?:/(?:browse-rules|rules)?)?(?:\?|/|$)|"
    r"rules\.utah\.gov(?:/(?:utah-administrative-code|publications/(?:administrative-rules-register|code-updates))?)?(?:/|$)|"
    r"adminrules\.utah\.gov(?:/(?:public/(?:home|search)(?:/.*)?|api/public/searchRuleDataTotal/[^/]+/Current%20Rules))?(?:/|$)|"
    r"govt\.westlaw\.com/calregs/(?:Index|Browse/Home/California/CaliforniaCodeofRegulations)(?:\?|/|$)|"
    r"iar\.iga\.in\.gov/code(?:/(?:current|2006))?(?:/|$)|"
    r"ilga\.gov/(?:(?:agencies/JCAR/(?:AdminCode|Parts|Sections))|commission/jcar/admincode)(?:\?|/|$)|"
    r"admincode\.legislature\.state\.al\.us/(?:administrative-code|agency|search)?(?:/|$)|"
    r"(?:www\.)?sos\.arkansas\.gov/rules-regulations(?:/|$)|"
    r"azsos\.gov/rules(?:/arizona-administrative-code)?(?:/|$)|"
    r"rules\.wyo\.gov/(?:Search\.aspx(?:\?mode=7)?|Agencies\.aspx)(?:\?|/|$)|"
    r"sharetngov\.tnsosfiles\.com/sos/(?:rules/(?:index\.htm|rules2\.htm|rules_list\.shtml|effectives/effectives\.htm)|pub/tar/index\.htm)(?:\?|/|$)|"
    r"apps\.azsos\.gov/public_services/(?:CodeTOC\.htm|Title_[\w.-]+\.htm)?$)",
    re.IGNORECASE,
)

_SD_RULE_INDEX_ROW_RE = re.compile(r"\b\d{2}:\d{2}\b")
_MT_RULE_INDEX_ROW_RE = re.compile(r"\bTitle\s+\d+\b", re.IGNORECASE)

_PDF_BINARY_HEADER_RE = re.compile(r"^\s*%PDF-\d\.\d", re.IGNORECASE)
_RTF_CONTENT_PREFIX_RE = re.compile(r"^\s*\{\\rtf", re.IGNORECASE)
_RTF_CONTENT_START_RE = re.compile(
    r"\b(?:chapter\s+\d+\.|article\s+\d+\.|title\s+\d+\.|r\d{1,2}-\d{1,2}-\d{2,4}\b)",
    re.IGNORECASE,
)
_RTF_SPLIT_WORD_RE = re.compile(r"\b([A-Za-z]{1,8})(?: |\n)([A-Za-z]{1,12})\b")
_RTF_EXTRACTION_NOISE_RE = re.compile(
    r"Times New Roman;|Arial;|Calibri;|Aptos;|Cambria Math;|Default Paragraph Font|Normal Table|panose",
    re.IGNORECASE,
)
_RTF_ARCHIVE_ARTIFACT_RE = re.compile(
    r"(?:\[Content_Types\]\.xml|_rels/\.rels|theme/theme(?:Manager|1)?\.xml)",
    re.IGNORECASE,
)
_RTF_INLINE_BINARY_BLOB_RE = re.compile(
    r"(?:\b(?:[0-9A-Fa-f]{2}){24,}\b|\b(?:504b0304|d0cf11e0a1b11ae1)[0-9A-Fa-f]{24,}\b)",
    re.IGNORECASE,
)
_RTF_MARKER_LINE_RE = re.compile(r"^RTF[0-9A-F_]{8,}$", re.IGNORECASE)
_RTF_STYLE_CATALOG_LINE_RE = re.compile(
    r"(?:^|;\s*)(?:Normal|Default Paragraph Font|Body Text|List Bullet|List Number|Heading\s+\d+|"
    r"Table(?:\s+[A-Za-z0-9]+)*|Grid Table|Plain Table|List Table|Colorful Grid|Colorful List|"
    r"Light (?:Shading|List|Grid)|Medium (?:Shading|List|Grid)|Dark List|TOC Heading|"
    r"Subtitle|Title|Quote|Intense Quote|Bibliography|Plain Text|Hyperlink|FollowedHyperlink|Mention|"
    r"Smart Hyperlink|Smart Link|Hashtag|Unresolved Mention)",
    re.IGNORECASE,
)
_RTF_COMMON_JOINED_WORDS = {
    "administrative",
    "applicability",
    "april",
    "article",
    "authority",
    "chapter",
    "codified",
    "definitions",
    "department",
    "environmental",
    "historical",
    "information",
    "legislature",
    "preface",
    "quality",
    "quarterly",
    "regulations",
    "secretary",
    "subject",
    "supplement",
    "through",
}
_RTF_LEADING_CONTENT_LINE_RE = re.compile(
    r"\b(?:article|chapter|title)\s+\d+\b|\bR\d{1,2}-\d{1,2}-\d{2,4}\b|"
    r"\b\d+\s+A\.A\.C\.\s+\d+\b|\badministrative\s+code\b|\bcode\s+of\s+regulations\b",
    re.IGNORECASE,
)
_BROWSER_CHALLENGE_HTML_RE = re.compile(
    r"just\s+a\s+moment|cf-browser-verification|cloudflare|enable\s+javascript\s+and\s+cookies",
    re.IGNORECASE,
)

_PDF_BINARY_TOKEN_RE = re.compile(
    r"\b\d+\s+\d+\s+obj\b|endobj|xref|trailer|startxref|/Filter\b|/Length\b",
    re.IGNORECASE,
)

# Curated admin-rules entrypoints for states that remain hard to recover via generic discovery.
_STATE_ADMIN_SOURCE_MAP: Dict[str, List[str]] = {
    "AL": [
        "http://www.alabamaadministrativecode.state.al.us/",
        "https://www.alabamaadministrativecode.state.al.us/",
        "https://admincode.legislature.state.al.us/",
        "https://admincode.legislature.state.al.us/administrative-code",
        "https://admincode.legislature.state.al.us/agency",
        "https://admincode.legislature.state.al.us/search",
        "https://www.sos.alabama.gov/alabama-administrative-code",
    ],
    "AZ": [
        "https://azsos.gov/rules/arizona-administrative-code",
        "https://azsos.gov/rules/",
        "https://azsos.gov/rules/arizona-administrative-register",
        "https://apps.azsos.gov/public_services/CodeTOC.htm",
        "https://apps.azsos.gov/public_services/Index/",
        "https://apps.azsos.gov/public_services/Title_02/2-01.pdf",
        "https://apps.azsos.gov/public_services/Title_02/2-02.pdf",
        "https://apps.azsos.gov/public_services/Title_02/2-03.pdf",
        "https://apps.azsos.gov/public_services/Title_02/2-04.pdf",
        "https://apps.azsos.gov/public_services/Title_02/2-12.pdf",
        "https://apps.azsos.gov/public_services/Title_08/8-03.pdf",
        "https://apps.azsos.gov/public_services/Title_09/9-30.pdf",
        "https://apps.azsos.gov/public_services/Title_06/6-11.rtf",
        "https://apps.azsos.gov/public_services/Title_13/13-01.rtf",
        "https://apps.azsos.gov/public_services/Title_15/15-02.rtf",
        "https://apps.azsos.gov/public_services/Title_15/15-03.rtf",
        "https://apps.azsos.gov/public_services/Title_15/15-05.pdf",
        "https://apps.azsos.gov/public_services/Title_15/15-07.pdf",
        "https://apps.azsos.gov/public_services/Title_17/17-04.pdf",
        "https://apps.azsos.gov/public_services/Title_18/18-01.rtf",
        "https://apps.azsos.gov/public_services/Title_18/18-04.rtf",
        "https://apps.azsos.gov/public_services/Title_04/4-08.pdf",
        "https://apps.azsos.gov/public_services/Title_07/7-02.rtf",
    ],
    "AK": [
        "https://www.akleg.gov/basis/aac.asp",
        "https://ltgov.alaska.gov/information/regulations/",
        "https://akrules.elaws.us/aac",
    ],
    "AR": [
        "https://codeofarrules.arkansas.gov/",
        "https://sos-rules-reg.ark.org/",
        "https://www.sos.arkansas.gov/rules-regulations/",
        "https://ark.org/rules_and_regs/index.php/rules/search/new",
    ],
    "CA": [
        "https://govt.westlaw.com/calregs/Index?transitionType=Default&contextData=%28sc.Default%29",
        "https://govt.westlaw.com/calregs/Index",
        "https://oal.ca.gov/publications/ccr/",
        "https://oal.ca.gov/publications/",
        "http://carules.elaws.us/search/allcode",
    ],
    "CO": [
        "https://www.sos.state.co.us/CCR/Welcome.do",
        "https://www.sos.state.co.us/CCR/NumericalDeptList.do",
        "https://www.sos.state.co.us/pubs/CCR/FAQs.html",
        "https://www.coloradosos.gov/CCR/Welcome.do",
        "https://www.coloradosos.gov/CCR/NumericalCCRDocList.do?deptID=0&agencyID=58",
    ],
    "CT": [
        "https://eregulations.ct.gov/eRegsPortal/Browse/RCSA",
        "https://eregulations.ct.gov/eRegsPortal/Search/RCSA",
        "https://eregulations.ct.gov/eRegsPortal/",
        "https://portal.ct.gov/Ethics/Statutes-and-Regulations/Statutes-and-Regulations/Regulations",
    ],
    "DE": [
        "https://regulations.delaware.gov/AdminCode",
        "https://regulations.delaware.gov/",
        "https://www.legis.delaware.gov/Offices/DivisionOfResearch/RegistrarOfRegulations",
    ],
    "FL": [
        "https://www.flrules.org/",
        "https://dos.fl.gov/offices/administrative-code-and-register/",
        "https://flrules.elaws.us/far/",
    ],
    "GA": [
        "https://rules.sos.ga.gov/gac",
        "https://rules.sos.ga.gov/",
    ],
    "HI": [
        "https://cca.hawaii.gov/hawaii-administrative-rules/",
        "https://ag.hawaii.gov/admin-rules/",
        "https://ag.hawaii.gov/publications/administrative-rules/",
        "https://ltgov.hawaii.gov/the-office/administrative-rules/",
        "https://labor.hawaii.gov/administrative-rules/",
    ],
    "ID": [
        "https://adminrules.idaho.gov/current-rules/",
        "https://adminrules.idaho.gov/rules/current/",
        "https://adminrules.idaho.gov/",
        "https://adminrules.idaho.gov/latest-bulletins/",
        "https://legislature.idaho.gov/statutesrules/idstat/Title67/T67CH52/",
    ],
    "IA": [
        "https://rules.iowa.gov/",
        "https://www.legis.iowa.gov/law/administrativeRules",
        "https://www.legis.iowa.gov/law/administrativeRules/agencies",
        "https://rules.iowa.gov/info/rules-publication",
        "https://rules.iowa.gov/info/track-proposed-rules",
    ],
    "IN": [
        "http://web.archive.org/web/20260120094721/https://iar.iga.in.gov/iac/irtoc.htm",
        "https://iar.iga.in.gov/code/current",
        "https://iar.iga.in.gov/code",
        "https://iar.iga.in.gov/code/2024",
        "https://iar.iga.in.gov/code/2006",
        "https://iar.iga.in.gov/code/current/10/1.5",
        "https://iar.iga.in.gov/code/current/16/2",
        "https://iar.iga.in.gov/code/current/16/4",
        "https://iar.iga.in.gov/code/current/25/1.1",
        "https://iar.iga.in.gov/code/current/25/1.5",
        "https://iar.iga.in.gov/code/current/25/7",
        "https://iar.iga.in.gov/code/current/31/1",
        "https://iar.iga.in.gov/code/current/35/1.1",
        "https://iar.iga.in.gov/code/current/35/1.3",
        "https://iar.iga.in.gov/code/current/35/14.1",
        "https://iar.iga.in.gov/code/current/45/1.1",
        "https://iar.iga.in.gov/code/current/45/2.1",
        "https://iar.iga.in.gov/code/current/45/2.2",
        "https://iar.iga.in.gov/code/current/45/3.1",
        "https://iar.iga.in.gov/code/current/45/4.1",
        "https://iar.iga.in.gov/code/current/45/8.1",
        "https://iar.iga.in.gov/code/current/50/2.1",
        "https://iar.iga.in.gov/register",
        "https://iar.iga.in.gov/sitemap.xml",
        "https://iar.iga.in.gov/iac//",
        "https://iar.iga.in.gov/iac/",
        "https://iar.iga.in.gov/iac/irtoc.htm",
        "https://iar.iga.in.gov/search",
        "https://iga.in.gov/legislative/laws/iac/",
    ],
    "IL": [
        "https://www.ilga.gov/agencies/JCAR/AdminCode",
        "https://www.ilga.gov/agencies/JCAR/Parts?TitleID=001&TitleDescription=TITLE%201:%20%20GENERAL%20PROVISIONS",
        "https://www.ilga.gov/agencies/JCAR/Sections?PartID=00100100&TitleDescription=TITLE%201:%20%20GENERAL%20PROVISIONS",
        "https://www.ilga.gov/agencies/JCAR/EntirePart?titlepart=00100100",
        "https://www.ilga.gov/commission/jcar/admincode/",
        "https://www.ilga.gov/commission/jcar/admincode/001/001001000A01000R.html",
    ],
    "LA": [
        "https://www.doa.la.gov/doa/osr/lac/",
        "https://www.doa.la.gov/doa/osr/",
        "https://www.sos.la.gov/BusinessServices/Pages/ReadAdministrativeRules.aspx",
        "https://www.sos.la.gov/ElectionsAndVoting/ReviewAdministrationAndHistory/ReadAdministrativeRules/Pages/default.aspx",
        "https://www.sos.la.gov/OurOffice/FindAdministrativeRules/Pages/default.aspx",
    ],
    "MA": [
        "https://www.sec.state.ma.us/divisions/pubs-regs/about-cmr.htm",
        "https://www.mass.gov/guides/code-of-massachusetts-regulations-cmr-by-number",
        "https://www.mass.gov/info-details/code-of-massachusetts-regulations-a-e",
        "https://www.mass.gov/info-details/code-of-massachusetts-regulations-f-j",
        "https://www.mass.gov/info-details/code-of-massachusetts-regulations-k-p",
        "https://www.mass.gov/info-details/code-of-massachusetts-regulations-q-z",
        "https://www.mass.gov/law-library/310-cmr",
        "https://www.mass.gov/regulations/310-CMR-100-adjudicatory-proceedings-0",
        "https://www.mass.gov/regulations/310-CMR-200-adopting-administrative-regulations",
        "https://www.mass.gov/regulations/310-CMR-300-access-to-and-confidentiality-of-department-records-and-files",
        "https://www.mass.gov/regulations/310-CMR-400-timely-action-schedule-and-fee-provisions-0",
        "https://www.mass.gov/regulations/310-CMR-700-air-pollution-control-0",
    ],
    "MD": [
        "https://dsd.maryland.gov/Pages/COMARHome.aspx",
        "https://dsd.maryland.gov/Pages/COMARSearch.aspx",
        "https://regs.maryland.gov/",
        "https://regs.maryland.gov/us/md/exec/comar",
        "https://regs.maryland.gov/us/md/exec/comar/01",
        "https://regs.maryland.gov/us/md/exec/comar/10",
        "https://regs.maryland.gov/us/md/exec/comar/26",
        "https://regs.maryland.gov/us/md/exec/comar/31",
    ],
    "ME": [
        "https://www.maine.gov/sos/rulemaking/agency-rules",
        "https://www.maine.gov/sos/rulemaking/agency-rules/department-administrative-financial-services-rules",
        "https://www.maine.gov/sos/rulemaking/agency-rules/department-environmental-protection-rules",
        "https://www.maine.gov/sos/rulemaking/agency-rules/department-health-and-human-services-rules",
    ],
    "MN": [
        "https://www.revisor.mn.gov/rules/",
        "https://www.revisor.mn.gov/rules/numerical/",
        "https://www.revisor.mn.gov/rules/1400/",
        "https://www.revisor.mn.gov/rules/7000/",
        "https://www.revisor.mn.gov/rules/8500/",
    ],
    "MO": [
        "https://www.sos.mo.gov/adrules/csr/csr",
        "https://www.sos.mo.gov/adrules/csr/current/1csr/1csr",
        "https://www.sos.mo.gov/adrules/csr/current/10csr/10csr",
        "https://www.sos.mo.gov/adrules/csr/current/19csr/19csr",
        "https://www.sos.mo.gov/cmsimages/adrules/csr/current/1csr/1c10-1.pdf",
        "https://www.sos.mo.gov/cmsimages/adrules/csr/current/1csr/1c15-3.pdf",
        "https://www.sos.mo.gov/cmsimages/adrules/csr/current/19csr/19c10-5.010.pdf",
    ],
    "NE": [
        "https://rules.nebraska.gov/",
        "https://rules.nebraska.gov/browse-rules",
    ],
    "MS": [
        "https://sos.ms.gov/regulation-enforcement/administrative-code",
        "https://www.sos.ms.gov/regulation-enforcement/administrative-code",
        "https://www.sos.ms.gov/adminsearch/default.aspx",
        "https://www.sos.ms.gov/adminsearch/",
    ],
    "NH": [
        "https://web.archive.org/web/20250308091642/https://gc.nh.gov/rules/",
        "https://web.archive.org/web/20250129103908/https://gc.nh.gov/rules/about_rules/listagencies.aspx",
        "https://web.archive.org/web/20250207090111/https://gc.nh.gov/rules/about_rules/listagencies.aspx",
        "https://web.archive.org/web/20250308091642/https://gc.nh.gov/rules/about_rules/listagencies.aspx",
        "https://web.archive.org/web/20250308091642/https://gc.nh.gov/rules/about_rules/checkrule.aspx",
        "https://web.archive.org/web/20250308091642/https://gc.nh.gov/rules/state_agencies/he-p300.html",
        "https://web.archive.org/web/20250308091642/https://gc.nh.gov/rules/state_agencies/agr100.html",
        "https://web.archive.org/web/20250308091642/https://gc.nh.gov/rules/state_agencies/agr200.html",
        "https://web.archive.org/web/20250308091642/https://gc.nh.gov/rules/state_agencies/env-wq300.html",
        "https://web.archive.org/web/20250308091642/https://gc.nh.gov/rules/state_agencies/env-wq400.html",
        "https://web.archive.org/web/20250308091642/https://gc.nh.gov/rules/state_agencies/rev100.html",
        "https://web.archive.org/web/20250308091642/https://gc.nh.gov/rules/state_agencies/saf-c200.html",
        "https://gencourt.state.nh.us/rules/state_agencies/env-ws1101-1105.html",
    ],
    "NM": [
        "https://web.archive.org/web/20260210051847/https://www.srca.nm.gov/nmac-home/",
        "https://web.archive.org/web/20260210051847/https://www.srca.nm.gov/nmac-home/nmac-titles/",
        "https://www.srca.nm.gov/nmac-home/",
        "https://www.srca.nm.gov/nmac-home/nmac-titles/",
    ],
    "NY": [
        "https://dos.ny.gov/new-york-codes-rules-and-regulations-nycrr",
        "https://dos.ny.gov/state-register",
        "http://nyrules.elaws.us/nycrr",
        "https://govt.westlaw.com/nycrr",
    ],
    "OK": [
        "https://www.sos.ok.gov/rules/default.aspx",
        "https://www.sos.ok.gov/rules/",
        "https://rules.ok.gov/",
        "https://rules.ok.gov/code",
    ],
    "KS": [
        "https://www.sos.ks.gov/publications/kansas-administrative-regulations.html",
        "https://www.sos.ks.gov/publications/agency-regulation-resources.html",
        "https://www.sos.ks.gov/publications/pubs_kar_Regs.aspx?KAR=7&Srch=Y",
        "https://www.sos.ks.gov/publications/pubs_kar_Regs.aspx?KAR=1-45&Srch=Y",
    ],
    "MT": [
        "https://rules.mt.gov/browse/collections/aec52c46-128e-4279-9068-8af5d5432d74",
        "https://rules.mt.gov/browse/collections/aec52c46-128e-4279-9068-8af5d5432d74/sections/ed446fdb-2d8d-4759-89ac-9cab3b21695c",
        "https://rules.mt.gov/browse/collections/aec52c46-128e-4279-9068-8af5d5432d74/sections/f15f6670-85c3-43bc-a946-4632329a8e23",
        "https://rules.mt.gov/browse/collections/aec52c46-128e-4279-9068-8af5d5432d74/sections/1892387a-b61e-4aa2-a1dd-d9f7a535fd42",
        "https://rules.mt.gov/browse/collections/aec52c46-128e-4279-9068-8af5d5432d74/sections/f504ae22-401c-4752-ac93-50e35903f1cd",
        "https://rules.mt.gov/browse/collections/aec52c46-128e-4279-9068-8af5d5432d74/sections/1f2ff5c5-b709-420b-bdd4-f6009ca7d33f",
        "https://rules.mt.gov/browse/collections/aec52c46-128e-4279-9068-8af5d5432d74/sections/b68c4d42-26f2-4fb4-b6a8-e1a2d4d265d2",
        "https://rules.mt.gov/browse/collections/aec52c46-128e-4279-9068-8af5d5432d74/sections/5eaf58c6-ae9f-4ebe-afe2-c617e962b390",
        "https://rules.mt.gov/browse/collections/aec52c46-128e-4279-9068-8af5d5432d74/sections/9af1b5dc-0d82-4413-bd9c-2cb707e5a8bd",
        "https://rules.mt.gov/browse/collections/aec52c46-128e-4279-9068-8af5d5432d74/sections/cd2f9808-ce8d-4a4a-b05c-fd9fa5d034e0",
        "https://rules.mt.gov/browse/collections/aec52c46-128e-4279-9068-8af5d5432d74/sections/11f11d0c-eb65-430a-baab-8728335a0c1b",
        "https://rules.mt.gov/browse/collections/aec52c46-128e-4279-9068-8af5d5432d74/sections/7e03f397-e356-4d0e-87b7-d4923e83599f",
        "https://rules.mt.gov/browse/collections/aec52c46-128e-4279-9068-8af5d5432d74/sections/c51b386c-09d3-476e-ab0b-ba97d644b619",
    ],
    "MI": [
        "https://www.michigan.gov/lara/bureau-list/moahr/admin-rules",
        "https://ars.apps.lara.state.mi.us/AdminCode/AdminCode",
        "https://ars.apps.lara.state.mi.us/Transaction/RFRTransaction?TransactionID=1306",
        "http://mirules.elaws.us/search/allcode",
    ],
    "RI": [
        "https://www.sos.ri.gov/divisions/open-government-center/rules-and-regulations",
        "https://rules.sos.ri.gov/regulations/part/510-00-00-1",
        "https://rules.sos.ri.gov/regulations/part/510-00-00-2",
        "https://rules.sos.ri.gov/regulations/part/510-00-00-3",
        "https://rules.sos.ri.gov/regulations/part/510-00-00-4",
        "https://rules.sos.ri.gov/regulations/part/510-00-00-5",
        "https://rules.sos.ri.gov/regulations/part/510-00-00-6",
        "https://rules.sos.ri.gov/regulations/part/510-00-00-7",
        "https://rules.sos.ri.gov/regulations/part/510-00-00-20",
    ],
    "SD": [
        "https://rules.sd.gov/",
        "https://rules.sd.gov/default.aspx",
        "https://sdlegislature.gov/Rules/Administrative",
        "https://sdlegislature.gov/Rules/Administrative/01:15",
        "https://sdlegislature.gov/Rules/Administrative/02:01",
        "https://sdlegislature.gov/Rules/Administrative/02:02",
        "https://sdlegislature.gov/Rules/Administrative/02:03",
        "https://sdlegislature.gov/Rules/Administrative/02:04",
        "https://sdlegislature.gov/Rules/Administrative/05:01",
    ],
    "TX": [
        "https://www.sos.state.tx.us/tac/index.shtml",
        "https://texreg.sos.state.tx.us/public/readtac$ext.ViewTAC",
        "https://www.sos.state.tx.us/texreg/guides/view-search-TAC.pdf",
        "https://texas-sos.appianportalsgov.com/rules-and-meetings?interface=VIEW_TAC",
        "https://texas-sos.appianportalsgov.com/rules-and-meetings?interface=SEARCH_TAC",
        "https://www.sos.state.tx.us/texreg/index.shtml",
        "https://www.sos.state.tx.us/texreg/transfers/index.shtml",
        "https://www.sos.state.tx.us/texreg/pdf/currview/index.shtml",
        "https://www.sos.state.tx.us/texreg/pdf/backview/index.shtml",
    ],
    "UT": [
        "https://adminrules.utah.gov/api/public/searchRuleDataTotal/R/Current%20Rules",
        "https://rules.utah.gov/",
        "https://adminrules.utah.gov/",
        "https://adminrules.utah.gov/public/search/c/Current+Rules",
        "https://adminrules.utah.gov/public/rule/R590-190/Current+Rules",
        "https://adminrules.utah.gov/public/rule/R51-2/Current+Rules",
        "https://adminrules.utah.gov/public/rule/R51-3/Current+Rules",
        "https://adminrules.utah.gov/public/rule/R51-4/Current+Rules",
        "https://rules.utah.gov/utah-administrative-code/",
        "https://rules.utah.gov/publications/administrative-rules-register/",
        "https://rules.utah.gov/publications/code-updates/",
    ],
    "VT": [
        "https://secure.vermont.gov/SOS/rules/",
        "https://secure.vermont.gov/SOS/rules/index.php",
        "https://secure.vermont.gov/SOS/rules/search.php",
        "https://secure.vermont.gov/SOS/rules/rssFeed.php",
        "https://secure.vermont.gov/SOS/rules/display.php?r=900",
        "https://secure.vermont.gov/SOS/rules/display.php?r=901",
        "https://secure.vermont.gov/SOS/rules/display.php?r=902",
        "https://secure.vermont.gov/SOS/rules/display.php?r=903",
        "https://secure.vermont.gov/SOS/rules/display.php?r=1032",
        "https://sos.vermont.gov/secretary-of-state-services/apa-rules/",
        "https://sos.vermont.gov/secretary-of-state-services/apa-rules/notices-of-rulemaking/",
        "https://aoa.vermont.gov/ICAR",
    ],
    "TN": [
        "http://web.archive.org/web/20250819093146/https://publications.tnsosfiles.com/rules/",
        "https://publications.tnsosfiles.com/rules/",
        "https://sos.tn.gov/publications/services/effective-rules-and-regulations-of-the-state-of-tennessee",
        "https://sos.tn.gov/publications/services/administrative-register",
        "https://sharetngov.tnsosfiles.com/sos/rules/index.htm",
        "https://sharetngov.tnsosfiles.com/sos/rules/rules2.htm",
        "https://sharetngov.tnsosfiles.com/sos/rules/0020/0020-01.20170126.pdf",
        "https://sharetngov.tnsosfiles.com/sos/pub/tar/index.htm",
        "https://www.tn.gov/sos/rules-and-regulations.html",
    ],
    "WY": [
        "http://web.archive.org/web/20260207213344/https://rules.wyo.gov/",
        "http://web.archive.org/web/20250917082256/https://rules.wyo.gov/Search.aspx",
        "https://rules.wyo.gov/Search.aspx?mode=7",
        "https://rules.wyo.gov/Help/Public/wyoming-administrative-rules-h.html",
    ],
}

_AZ_LATE_RETRY_DOCUMENT_URLS: tuple[str, ...] = (
    "https://apps.azsos.gov/public_services/Title_02/2-12.pdf",
    "https://apps.azsos.gov/public_services/Title_02/2-04.pdf",
    "https://apps.azsos.gov/public_services/Title_15/15-05.rtf",
    "https://apps.azsos.gov/public_services/Title_18/18-04.rtf",
    "https://apps.azsos.gov/public_services/Title_15/15-03.rtf",
    "https://apps.azsos.gov/public_services/Title_07/7-02.rtf",
    "https://apps.azsos.gov/public_services/Title_18/18-01.rtf",
)
_AZ_LATE_RETRY_MIN_TIMEOUT_S = 45.0
_AZ_LATE_RETRY_MAX_TIMEOUT_S = 70.0
_MS_ADMINSEARCH_INDEX_URL = "https://www.sos.ms.gov/adminsearch/default.aspx"
_MS_ADMINSEARCH_SERVICE_URL = "https://www.sos.ms.gov/adminsearch/AdminSearchService.asmx/CodeSearch"
_MS_ADMINSEARCH_DOCUMENT_BASE_URL = "https://www.sos.ms.gov/adminsearch/ACCode/"
_MS_ADMINSEARCH_DEFAULT_AGENCY_VALUES: tuple[str, ...] = ("54 ", "15 ")

# States that still need broader, controlled acceptance during recovery runs.
_RECOVERY_RELAXED_STATES = {"AL", "AZ", "HI", "MS", "MT", "NH", "SD", "TN"}

# These states are better served by direct admin-rule discovery than by the
# delegated state-laws scrape, which can consume the bounded budget on
# statute-specific work before admin-rule recovery starts.
_DIRECT_AGENTIC_RECOVERY_STATES = {"AL", "AR", "AZ", "CA", "CO", "CT", "GA", "HI", "ID", "KS", "LA", "MD", "ME", "MI", "MN", "MO", "MS", "NE", "OK", "TN", "UT", "VT", "WY"}


def _is_admin_rule_statute(statute: Dict[str, Any]) -> bool:
    legal_area = str(statute.get("legal_area") or "")
    code_name = str(statute.get("code_name") or "")
    section_name = str(statute.get("section_name") or statute.get("short_title") or "")
    official_cite = str(statute.get("official_cite") or "")
    source_url = str(statute.get("source_url") or "")

    if _NON_ADMIN_CODE_NAME_RE.search(code_name):
        return False
    if source_url and _NON_ADMIN_SOURCE_URL_RE.search(source_url):
        return False

    haystack = " ".join([legal_area, code_name, section_name, official_cite, source_url])
    if _ADMIN_RULE_TEXT_RE.search(haystack):
        return True

    # Preserve records already tagged as regulations by state-specific scrapers.
    structured_data = statute.get("structured_data") or {}
    if isinstance(structured_data, dict):
        code_type = str(structured_data.get("code_type") or structured_data.get("type") or "")
        if code_type and _ADMIN_RULE_TEXT_RE.search(code_type):
            return True

    return False


def _resolve_admin_output_dir(output_dir: Optional[str] = None) -> Path:
    if output_dir:
        return Path(output_dir).expanduser().resolve()
    return get_canonical_legal_corpus("state_admin_rules").default_local_root()


def _build_admin_fallback_jsonld_payload(*, state_code: str, state_name: str, statute: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    full_text = str(statute.get("full_text") or "").strip()
    section_number = str(statute.get("section_number") or "").strip()
    section_name = str(statute.get("section_name") or "").strip()
    code_name = str(statute.get("code_name") or "").strip()
    source_url = str(statute.get("source_url") or "").strip()
    official_cite = str(statute.get("official_cite") or "").strip()
    statute_id = str(statute.get("statute_id") or "").strip() or section_number or section_name

    if not (full_text or section_name or section_number or statute_id):
        return None

    title_parts = [part for part in [state_name or state_code, code_name, section_number] if part]
    title = " - ".join(title_parts) or f"{state_code} administrative rule"

    payload: Dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "Legislation",
        "legislationType": "StateAdministrativeRule",
        "legislationJurisdiction": f"US-{state_code}",
        "name": title,
        "identifier": statute_id or title,
        "description": section_name or full_text[:500],
        "text": full_text or section_name,
        "url": source_url,
        "sourceUrl": source_url,
        "sectionNumber": section_number,
        "sectionName": section_name,
    }

    if source_url:
        payload["@id"] = source_url
        payload["sameAs"] = source_url
    if code_name:
        payload["legislationIdentifier"] = code_name
    if official_cite:
        payload["citation"] = official_cite

    return payload


def _enrich_admin_rule_structured_data(*, state_code: str, state_name: str, statute: Dict[str, Any]) -> None:
    section_number = str(statute.get("section_number") or "").strip()
    section_name = str(statute.get("section_name") or statute.get("short_title") or "").strip()
    source_url = str(statute.get("source_url") or "").strip()
    full_text = str(statute.get("full_text") or statute.get("text") or "").strip()
    statute_id = str(statute.get("statute_id") or "").strip()
    code_name = str(statute.get("code_name") or "").strip()
    official_cite = str(statute.get("official_cite") or "").strip()

    if section_number:
        statute["section_number"] = section_number
    if section_name:
        statute["section_name"] = section_name
        statute.setdefault("short_title", section_name)
    if source_url:
        statute["source_url"] = source_url
    if full_text:
        statute["full_text"] = full_text

    if section_name and not str(statute.get("title") or "").strip():
        statute["title"] = section_name
    if full_text and not str(statute.get("text") or "").strip():
        statute["text"] = full_text
    if source_url:
        if not str(statute.get("url") or "").strip():
            statute["url"] = source_url
        if not str(statute.get("sourceUrl") or "").strip():
            statute["sourceUrl"] = source_url
    if section_number and not str(statute.get("sectionNumber") or "").strip():
        statute["sectionNumber"] = section_number
    if section_name and not str(statute.get("sectionName") or "").strip():
        statute["sectionName"] = section_name
    if statute_id and not str(statute.get("identifier") or "").strip():
        statute["identifier"] = statute_id
    if official_cite and not str(statute.get("citation") or "").strip():
        statute["citation"] = official_cite
    if code_name and not str(statute.get("codeName") or "").strip():
        statute["codeName"] = code_name
    if not str(statute.get("description") or "").strip():
        description = section_name or full_text[:500]
        if description:
            statute["description"] = description

    structured_data = statute.get("structured_data")
    if not isinstance(structured_data, dict):
        structured_data = {}

    if str(structured_data.get("type") or "").strip() == "":
        structured_data["type"] = "regulation"

    payload = structured_data.get("jsonld")
    if not isinstance(payload, dict):
        payload = _build_admin_fallback_jsonld_payload(
            state_code=state_code,
            state_name=state_name,
            statute=statute,
        )
    else:
        payload = dict(payload)

    if isinstance(payload, dict):
        payload.setdefault("@context", "https://schema.org")
        payload.setdefault("@type", "Legislation")
        payload.setdefault("legislationType", "StateAdministrativeRule")
        payload.setdefault("legislationJurisdiction", f"US-{state_code}")
        if statute_id:
            payload.setdefault("identifier", statute_id)
        if section_number:
            payload.setdefault("sectionNumber", section_number)
        if section_name:
            payload.setdefault("sectionName", section_name)
            payload.setdefault("name", section_name)
        if full_text:
            payload.setdefault("text", full_text)
            payload.setdefault("description", section_name or full_text[:500])
        if code_name:
            payload.setdefault("legislationIdentifier", code_name)
        if source_url:
            payload.setdefault("url", source_url)
            payload.setdefault("sourceUrl", source_url)
            payload.setdefault("sameAs", source_url)
            payload.setdefault("@id", source_url)
        if official_cite:
            payload.setdefault("citation", official_cite)

        structured_data["jsonld"] = payload

    citations = structured_data.get("citations")
    if not isinstance(citations, dict):
        citations = {}
    official_cite = str(statute.get("official_cite") or "").strip()
    if official_cite:
        existing_official = citations.get("official")
        if isinstance(existing_official, list):
            if official_cite not in existing_official:
                citations["official"] = [*existing_official, official_cite]
        else:
            citations["official"] = [official_cite]
    if citations:
        structured_data["citations"] = citations

    statute["structured_data"] = structured_data


def _normalize_admin_rule_payloads(scraped_rules: List[Dict[str, Any]]) -> None:
    for state_block in scraped_rules:
        if not isinstance(state_block, dict):
            continue
        state_code = str(state_block.get("state_code") or "").strip().upper()
        state_name = str(state_block.get("state_name") or "").strip()
        statutes = state_block.get("statutes") or []
        if not state_code or not isinstance(statutes, list):
            continue
        for statute in statutes:
            if not isinstance(statute, dict):
                continue
            _enrich_admin_rule_structured_data(
                state_code=state_code,
                state_name=state_name or state_code,
                statute=statute,
            )


def _write_state_admin_jsonld_files(scraped_rules: List[Dict[str, Any]], jsonld_dir: Path) -> List[str]:
    written: List[str] = []
    for state_block in scraped_rules:
        state_code = str(state_block.get("state_code") or "").strip().upper()
        state_name = str(state_block.get("state_name") or "").strip()
        statutes = state_block.get("statutes") or []
        if not state_code or not isinstance(statutes, list):
            continue

        out_path = jsonld_dir / f"STATE-{state_code}.jsonld"
        lines_written = 0
        with out_path.open("w", encoding="utf-8") as handle:
            for statute in statutes:
                if not isinstance(statute, dict):
                    continue
                structured_data = statute.get("structured_data") or {}
                payload = None
                if isinstance(structured_data, dict):
                    payload = structured_data.get("jsonld")
                if not isinstance(payload, dict):
                    payload = _build_admin_fallback_jsonld_payload(
                        state_code=state_code,
                        state_name=state_name,
                        statute=statute,
                    )
                if not isinstance(payload, dict):
                    continue
                if str(payload.get("legislationType") or "").strip() == "":
                    payload["legislationType"] = "StateAdministrativeRule"
                handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
                lines_written += 1

        if lines_written > 0:
            written.append(str(out_path))
        else:
            out_path.unlink(missing_ok=True)

    return written


def _collect_admin_source_diagnostics(states: List[str]) -> Dict[str, Dict[str, Any]]:
    try:
        from .state_scrapers import GenericStateScraper, get_scraper_for_state
    except Exception as exc:
        return {
            "_diagnostics_error": {
                "error": str(exc),
            }
        }

    diagnostics: Dict[str, Dict[str, Any]] = {}
    for state_code in states:
        state_name = US_STATES.get(state_code, state_code)
        try:
            scraper = get_scraper_for_state(state_code, state_name)
            if not scraper:
                scraper = GenericStateScraper(state_code, state_name)

            code_list = list(scraper.get_code_list() or [])
            admin_candidates: List[str] = []
            for item in code_list:
                if not isinstance(item, dict):
                    continue
                code_name = str(item.get("name") or "")
                code_url = str(item.get("url") or "")
                code_type = str(item.get("type") or "")
                text = " ".join([code_name, code_url, code_type])
                if _ADMIN_RULE_TEXT_RE.search(text):
                    admin_candidates.append(code_name or code_url)
                    continue
                identify = getattr(scraper, "_identify_legal_area", None)
                if callable(identify) and str(identify(code_name)).strip().lower() == "administrative":
                    admin_candidates.append(code_name or code_url)

            admin_candidates = [value for value in admin_candidates if str(value or "").strip()]
            diagnostics[state_code] = {
                "total_code_sources": len(code_list),
                "admin_candidate_sources": len(admin_candidates),
                "admin_candidate_examples": admin_candidates[:5] or None,
            }
        except Exception as exc:
            diagnostics[state_code] = {
                "error": str(exc),
            }

    return diagnostics


def _filter_admin_state_blocks(
    raw_data: List[Dict[str, Any]],
    *,
    max_rules: Optional[int],
    min_full_text_chars: int,
    require_substantive_text: bool,
) -> tuple[List[Dict[str, Any]], int, List[str]]:
    filtered_data: List[Dict[str, Any]] = []
    admin_rule_count = 0
    zero_rule_states: List[str] = []

    for state_block in raw_data:
        if not isinstance(state_block, dict):
            continue
        state_code = str(state_block.get("state_code") or "").upper()
        statutes = list(state_block.get("statutes") or [])
        admin_statutes: List[Dict[str, Any]] = []
        for statute in statutes:
            if not isinstance(statute, dict):
                continue
            if not _is_admin_rule_statute(statute):
                continue
            if require_substantive_text and not _is_substantive_admin_statute(
                statute,
                min_chars=int(min_full_text_chars),
            ):
                continue
            admin_statutes.append(statute)
        if max_rules and max_rules > 0:
            admin_statutes = admin_statutes[: int(max_rules)]

        out_block = dict(state_block)
        out_block["title"] = f"{US_STATES.get(state_code, state_code)} Administrative Rules"
        out_block["source"] = "Official State Administrative Rule Sources"
        out_block["statutes"] = admin_statutes
        out_block["rules_count"] = len(admin_statutes)
        filtered_data.append(out_block)

        admin_rule_count += len(admin_statutes)
        if len(admin_statutes) == 0 and state_code:
            zero_rule_states.append(state_code)

    return filtered_data, admin_rule_count, zero_rule_states


def _ensure_target_state_blocks(
    filtered_data: List[Dict[str, Any]],
    *,
    selected_states: List[str],
) -> tuple[List[Dict[str, Any]], List[str]]:
    """Ensure every targeted state has a placeholder block for fallback recovery."""
    out = list(filtered_data)
    present_states = {
        str((item or {}).get("state_code") or "").upper()
        for item in out
        if isinstance(item, dict)
    }
    added_zero_states: List[str] = []

    for state_code in selected_states:
        state_code = str(state_code or "").upper()
        if not state_code or state_code in present_states:
            continue
        out.append(
            {
                "state_code": state_code,
                "state_name": US_STATES.get(state_code, state_code),
                "title": f"{US_STATES.get(state_code, state_code)} Administrative Rules",
                "source": "Official State Administrative Rule Sources",
                "source_url": None,
                "scraped_at": datetime.now().isoformat(),
                "statutes": [],
                "rules_count": 0,
                "schema_version": "1.0",
                "normalized": True,
            }
        )
        added_zero_states.append(state_code)
        present_states.add(state_code)

    return out, added_zero_states


def _agentic_domains_for_state(state_code: str) -> List[str]:
    low = str(state_code or "").lower()
    if not low:
        return []
    return [
        f"{low}.gov",
        f"state.{low}.us",
        f"admincode.{low}.gov",
        "rules.state.us",
    ]


def _host_matches_allowed(host: str, allowed_hosts: set[str]) -> bool:
    host_value = str(host or "").strip().lower().strip(".")
    if not host_value:
        return False
    return any(
        host_value == allowed or host_value.endswith(f".{allowed}")
        for allowed in allowed_hosts
        if allowed
    )


def _allowed_discovery_hosts_for_state(state_code: str, state_name: str) -> set[str]:
    allowed_hosts: set[str] = {"web.archive.org"}

    for url in _extract_seed_urls_for_state(state_code, state_name):
        host = urlparse(str(url or "").strip()).netloc.lower().strip(".")
        if host:
            allowed_hosts.add(host)

    for url in _template_admin_urls_for_state(state_code):
        host = urlparse(str(url or "").strip()).netloc.lower().strip(".")
        if host:
            allowed_hosts.add(host)

    official_url = str(_get_official_state_url(state_code) or "").strip()
    official_host = ""
    if official_url and not _is_non_admin_seed_url(official_url):
        official_host = urlparse(official_url).netloc.lower().strip(".")
    if official_host:
        allowed_hosts.add(official_host)
    if str(state_code or "").upper() == "HI":
        allowed_hosts.add("files.hawaii.gov")
    if str(state_code or "").upper() == "ID":
        allowed_hosts.add("stagingdfmmainsa.blob.core.windows.net")
        allowed_hosts.add("proddfmmainsa.blob.core.windows.net")

    return {host for host in allowed_hosts if host}


def _url_allowed_for_state(url: str, allowed_hosts: set[str]) -> bool:
    value = str(url or "").strip()
    if not value or _is_non_admin_seed_url(value):
        return False
    host = urlparse(value).netloc.lower().strip(".")
    if not host:
        return False
    if not _is_allowed_arizona_rule_candidate_url(value):
        return False
    return _host_matches_allowed(host, allowed_hosts)


def _is_allowed_arizona_rule_candidate_url(url: str) -> bool:
    value = str(url or "").strip()
    if not value:
        return False
    parsed = urlparse(value)
    host = parsed.netloc.lower().strip(".")
    path = parsed.path or ""
    normalized_path = path.rstrip("/") or "/"

    if host == "apps.azsos.gov":
        if _AZ_OFFICIAL_DOCUMENT_PATH_RE.search(path):
            return True
        if normalized_path.lower() in {
            "/public_services/codetoc.htm",
            "/public_services/index",
        }:
            return True
        return False

    if host in {"azsos.gov", "www.azsos.gov"}:
        return normalized_path.lower().startswith("/rules")

    return True


def _agentic_query_for_state(state_code: str) -> str:
    state_name = US_STATES.get(state_code, state_code)
    base = f"{state_name} administrative code regulations agency rules"
    hints = _query_hints_for_state(state_code)
    if not hints:
        return base
    suffix = " ".join(hints[:3])
    return f"{base} {suffix}".strip()


def _query_hints_for_state(state_code: str) -> List[str]:
    raw = str(os.getenv("LEGAL_SCRAPER_QUERY_HINTS_JSON") or "").strip()
    if not raw:
        return []
    try:
        payload = json.loads(raw)
    except Exception:
        return []
    if not isinstance(payload, dict):
        return []
    items = payload.get(str(state_code or "").upper()) or []
    if not isinstance(items, list):
        return []
    deduped: List[str] = []
    seen = set()
    for item in items:
        text = str(item or "").strip()
        key = text.lower()
        if not text or key in seen:
            continue
        seen.add(key)
        deduped.append(text)
    return deduped[:6]


def _query_target_terms_for_state(state_code: str) -> List[str]:
    target_terms = ["administrative", "regulations", "rules", "code"]
    for hint in _query_hints_for_state(state_code):
        for token in re.split(r"[^A-Za-z0-9]+", hint):
            value = str(token or "").strip().lower()
            if len(value) < 4:
                continue
            if value not in target_terms:
                target_terms.append(value)
    return target_terms[:12]


def _max_fetch_cap_for_state(state_code: str) -> Optional[int]:
    state_key = str(state_code or "").strip().upper()
    if not state_key:
        return None

    raw_json = str(os.getenv("LEGAL_ADMIN_RULES_MAX_FETCH_PER_STATE_JSON") or "").strip()
    if raw_json:
        try:
            payload = json.loads(raw_json)
        except Exception:
            payload = None
        if isinstance(payload, dict):
            state_value = payload.get(state_key)
            try:
                if state_value is not None:
                    cap_value = int(state_value)
                    if cap_value > 0:
                        return cap_value
            except Exception:
                pass

    raw_default = str(os.getenv("LEGAL_ADMIN_RULES_MAX_FETCH_PER_STATE") or "").strip()
    if not raw_default:
        return None
    try:
        cap_value = int(raw_default)
    except Exception:
        return None
    if cap_value <= 0:
        return None
    return cap_value


def _extract_seed_urls_for_state(state_code: str, state_name: str) -> List[str]:
    urls: List[str] = []
    try:
        urls.extend(_STATE_ADMIN_SOURCE_MAP.get(str(state_code or "").upper(), []))

        from .state_scrapers import GenericStateScraper, get_scraper_for_state

        scraper = get_scraper_for_state(state_code, state_name)
        if scraper is None:
            scraper = GenericStateScraper(state_code, state_name)
        base_url = str(scraper.get_base_url() or "").strip()
        if base_url and not _is_non_admin_seed_url(base_url):
            urls.append(base_url)
        code_list = list(scraper.get_code_list() or [])
        admin_priority_urls: List[str] = []
        identify = getattr(scraper, "_identify_legal_area", None)
        for item in code_list:
            if not isinstance(item, dict):
                continue
            code_name = str(item.get("name") or "")
            value = str(item.get("url") or "").strip()
            code_type = str(item.get("type") or "")
            if not value:
                continue
            if _is_non_admin_seed_url(value):
                continue
            signal = " ".join([code_name, code_type, value])
            if _ADMIN_RULE_TEXT_RE.search(signal):
                admin_priority_urls.append(value)
                continue
            if callable(identify) and str(identify(code_name)).strip().lower() == "administrative":
                admin_priority_urls.append(value)

        # For admin discovery, only inherit scraper URLs that already carry
        # administrative-rule signals. Generic statute index URLs tend to
        # divert the bounded crawl back into state-laws territory.
        urls.extend(admin_priority_urls)

        # Add deterministic admin URL templates as seed entrypoints too.
        urls.extend(
            url
            for url in _template_admin_urls_for_state(state_code)
            if not _is_non_admin_seed_url(url)
        )
    except Exception:
        pass

    deduped: List[str] = []
    seen = set()
    for value in urls:
        key = str(value).strip().lower()
        if not key or key in seen:
            continue
        if not key.startswith(("http://", "https://")):
            continue
        if _is_non_admin_seed_url(value):
            continue
        seen.add(key)
        deduped.append(value)
    return deduped[:24]


def _template_admin_urls_for_state(state_code: str) -> List[str]:
    base_url = str(_get_official_state_url(state_code) or "").strip()
    if not base_url:
        return []
    if _is_non_admin_seed_url(base_url):
        return []
    if not base_url.endswith("/"):
        base_url = base_url + "/"

    tails = [
        "rules",
        "regulations",
        "administrative-code",
        "code-of-regulations",
        "agency-rules",
        "policies",
        "departments",
    ]
    urls = [base_url.rstrip("/")]
    for tail in tails:
        urls.append(base_url + tail)
    return urls


def _is_non_admin_seed_url(url: str) -> bool:
    value = str(url or "").strip()
    if not value:
        return False
    lower_value = value.lower()
    if _NON_ADMIN_SOURCE_URL_RE.search(value):
        return True
    parsed = urlparse(value)
    host = parsed.netloc.lower()
    path = parsed.path or "/"
    normalized_path = path.rstrip("/") or "/"
    query = parsed.query or ""
    if host == "legislature.az.gov":
        return True
    if host == "www.azleg.gov" and _AZLEG_NON_ADMIN_SEED_PATH_RE.fullmatch(normalized_path):
        return True
    if host in {"www.legis.ga.gov", "legis.ga.gov"}:
        return True
    if host in {"leg.mt.gov", "www.leg.mt.gov"}:
        return True
    if host in {"legislature.in.gov", "www.legislature.in.gov"}:
        return True
    if host in {"legislature.nm.gov", "nmlegis.gov", "www.nmlegis.gov"}:
        return True
    if host in {"legislature.ak.gov", "legis.state.ak.us", "www.legis.state.ak.us"}:
        return True
    if host in {"legislature.ar.gov", "arkleg.state.ar.us", "www.arkleg.state.ar.us"}:
        return True
    if host == "legislature.tn.gov":
        return True
    if host in {"www.capitol.tn.gov", "capitol.tn.gov"} and normalized_path.lower() == "/legislation/archives.html":
        return True
    if host in {"www.tn.gov", "tn.gov"} and normalized_path.lower() in {
        "/",
        "/tga",
        "/sos/rules-and-regulations.html",
        "/sos/rules/tnnewrules.xml",
    }:
        return True
    if host in {"www.wyoleg.gov", "wyoleg.gov", "legislature.wy.gov"}:
        return True
    if host == "rules.wyo.gov":
        handler = str((parse_qs(query).get("handler") or [""])[0]).strip().lower()
        mode = str((parse_qs(query).get("mode") or [""])[0]).strip()
        if normalized_path == "/":
            return True
        if normalized_path.lower() == "/search.aspx" and handler != "search" and mode != "7":
            return True
    if host == "web.archive.org":
        if re.search(r"/https://publications\.tnsosfiles\.com/rules/?$", lower_value):
            return True
        if re.search(r"/https://rules\.wyo\.gov/?$", lower_value):
            return True
        if re.search(r"/https://rules\.wyo\.gov/search\.aspx(?:$|[^a-z0-9])", lower_value) and "mode=7" not in lower_value:
            return True
    if host == "leginfo.legislature.ca.gov":
        if _CA_NON_RULE_LEGISLATURE_PATH_RE.fullmatch(normalized_path):
            return True
        if re.search(r"(?:^|[?&])(tocCode|lawCode|sectionNum)=", query, re.IGNORECASE):
            return True
    return False


def _new_hampshire_archived_rule_slug(url: str) -> str:
    value = str(url or "").strip()
    if not _NH_ARCHIVED_RULE_CHAPTER_URL_RE.search(value):
        return ""
    parsed = urlparse(value)
    filename = Path(unquote(parsed.path or "")).name
    if not filename.lower().endswith(".html"):
        return ""
    return filename[:-5].strip().lower()


def _is_new_hampshire_archived_rule_leaf_url(url: str) -> bool:
    slug = _new_hampshire_archived_rule_slug(url)
    return bool(slug and re.search(r"\d", slug))


def _looks_like_new_hampshire_archived_rule_inventory(*, text: str, title: str, url: str) -> bool:
    if not _NH_ARCHIVED_RULE_CHAPTER_URL_RE.search(str(url or "").strip()):
        return False
    if _is_new_hampshire_archived_rule_leaf_url(url):
        return False
    if not str(text or "").strip() and not str(title or "").strip():
        return True
    hay = " ".join([str(title or ""), str(text or "")]).lower()
    chapter_hits = len(re.findall(r"\bchapter\s+[A-Za-z-]+\s*\d{3}\b", hay, re.IGNORECASE))
    return "table of contents" in hay or chapter_hits >= 3


def _normalize_new_hampshire_archived_wayback_url(url: str) -> str:
    value = str(url or "").strip()
    if value.startswith("http://web.archive.org/"):
        return "https://" + value[len("http://") :]
    return value


def _wayback_iframe_replay_url(url: str) -> str:
    value = str(url or "").strip()
    if not value or "web.archive.org/web/" not in value:
        return ""
    if "/if_/" in value or re.search(r"/web/\d+if_/https?://", value, re.IGNORECASE):
        return value
    return re.sub(r"(web\.archive\.org/web/\d+)/(https?://)", r"\1if_/\2", value, count=1)


def _looks_like_wayback_shell_page(*, title: str, text: str) -> bool:
    hay = " ".join([str(title or ""), str(text or "")]).lower()
    return (
        "wayback machine" in hay
        and "internet archive" in hay
        and "ask the publishers" in hay
    )


def _looks_like_new_hampshire_blocked_page(*, title: str, text: str) -> bool:
    hay = " ".join([str(title or ""), str(text or "")]).lower()
    return (
        "error 403" in hay
        and "web page blocked" in hay
        and "robots.txt" in hay
    )


def _wayback_replay_original_url(url: str) -> str:
    value = str(url or "").strip()
    match = re.match(r"^https?://web\.archive\.org/web/\d+(?:if_|id_)?/(https?://.+)$", value, re.IGNORECASE)
    if not match:
        return ""
    return str(match.group(1) or "").strip()


def _wayback_replay_timestamp(url: str) -> str:
    value = str(url or "").strip()
    match = re.match(r"^https?://web\.archive\.org/web/(\d{14})(?:if_|id_)?/https?://", value, re.IGNORECASE)
    if not match:
        return ""
    return str(match.group(1) or "").strip()


def _wayback_replay_url(timestamp: str, original_url: str) -> str:
    ts = str(timestamp or "").strip()
    original = str(original_url or "").strip()
    if not ts or not original:
        return ""
    return f"https://web.archive.org/web/{ts}/{original}"


def _discover_wayback_capture_candidates(url: str, *, limit: int = 5) -> List[str]:
    value = str(url or "").strip()
    original_url = _wayback_replay_original_url(value) or value
    if not original_url:
        return []

    headers = {"User-Agent": "Mozilla/5.0"}
    api_url = "https://web.archive.org/cdx/search/cdx"
    query_urls = [original_url]
    if "://gc.nh.gov/" in original_url:
        query_urls.append(original_url.replace("://gc.nh.gov/", "://www.gc.nh.gov/", 1))
        query_urls.append(original_url.replace("://gc.nh.gov/", "://www.gencourt.state.nh.us/", 1))
    elif "://www.gc.nh.gov/" in original_url:
        query_urls.append(original_url.replace("://www.gc.nh.gov/", "://gc.nh.gov/", 1))
        query_urls.append(original_url.replace("://www.gc.nh.gov/", "://www.gencourt.state.nh.us/", 1))
    elif "://www.gencourt.state.nh.us/" in original_url:
        query_urls.append(original_url.replace("://www.gencourt.state.nh.us/", "://gc.nh.gov/", 1))

    candidates: List[str] = []
    seen: set[str] = {value}
    for query_url in query_urls:
        try:
            response = requests.get(
                api_url,
                params={
                    "url": query_url,
                    "output": "json",
                    "fl": "timestamp,original,statuscode,mimetype",
                    "filter": "statuscode:200",
                    "limit": str(max(1, int(limit or 1)) * 2),
                    "from": "2024",
                    "to": "2026",
                    "collapse": "digest",
                },
                timeout=25,
                headers=headers,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception:
            continue

        if not isinstance(payload, list) or len(payload) <= 1:
            continue
        for row in payload[1:]:
            if not isinstance(row, list) or len(row) < 2:
                continue
            replay_url = _normalize_new_hampshire_archived_wayback_url(
                _wayback_replay_url(str(row[0] or "").strip(), str(row[1] or query_url).strip())
            )
            if not replay_url or replay_url in seen:
                continue
            seen.add(replay_url)
            candidates.append(replay_url)
            if len(candidates) >= max(1, int(limit or 1)):
                return candidates
    return candidates


def _score_candidate_url(url: str) -> int:
    value = str(url or "").lower()
    if not value:
        return 0
    if _NON_ADMIN_SOURCE_URL_RE.search(value):
        return -25
    score = 0
    parsed = urlparse(str(url or "").strip())
    host = parsed.netloc.lower()
    if _BAD_DISCOVERY_DOMAIN_RE.search(host):
        return -20
    path = parsed.path or ""
    normalized_path = path.rstrip("/") or "/"
    query = parsed.query or ""
    if _ADMIN_RULE_TEXT_RE.search(value):
        score += 3
    if ".gov" in value or ".us" in value:
        score += 2
    if "/rule" in value or "/reg" in value or "admin" in value:
        score += 2
    if any(
        token in value
        for token in (
            "/part/",
            "/section/",
            "/sections/",
            "display.php",
            "/browse/collections/",
            "/code/",
            "/gac/",
            "/transfers/",
            "/pdf/currview/",
            "/pdf/backview/",
        )
    ):
        score += 2
    if "title" in value or "chapter" in value or "article" in value:
        score += 1
    if host == "adminrules.utah.gov" and path.lower().startswith("/public/search"):
        # Search indexes are useful discovery surfaces, but real rule detail pages
        # should always outrank them when both are available.
        score += 3
        if any(token in value for token in ("current%20rules", "/proposed", "/emergency")):
            score += 1
    if host == "adminrules.utah.gov" and _UT_RULE_DETAIL_PATH_RE.search(path):
        score += 8
    if host == "rules.utah.gov" and _UT_NON_RULE_NEWS_PATH_RE.search(path):
        score += 10
    if host == "ltgov.alaska.gov" and normalized_path.lower() == "/information/regulations":
        score += 4
    if host == "www.akleg.gov" and normalized_path.lower() == "/basis/aac.asp":
        score += 6
        query_lower = query.lower()
        sec_start = str((parse_qs(query).get("secStart") or [""])[0]).strip()
        sec_end = str((parse_qs(query).get("secEnd") or [""])[0]).strip()
        if "media=print" in query_lower and _AK_AAC_SECTION_PATH_RE.fullmatch(f"/aac/{sec_start}") and sec_start == sec_end:
            score += 8
    if host == "eregulations.ct.gov":
        if _CT_EREGS_ROOT_PATH_RE.fullmatch(path):
            score += 6
        elif _CT_EREGS_TITLE_PATH_RE.fullmatch(path):
            score += 8
        elif _CT_EREGS_SUBTITLE_PATH_RE.fullmatch(path):
            score += 10
        elif _CT_EREGS_SECTION_PATH_RE.fullmatch(path):
            score += 14
    if host in {"www.sos.la.gov", "sos.la.gov"} and "/publisheddocuments/" in path.lower() and path.lower().endswith(".pdf"):
        score += 8
        file_name = unquote(path.rsplit("/", 1)[-1]).lower()
        if any(token in file_name for token in ("title", "chapter", "rule", "administrative", "corporations", "ucc")):
            score += 4
    if host in {"www.sos.state.co.us", "www.coloradosos.gov"}:
        query_params = parse_qs(parsed.query or "")
        if _CO_CCR_WELCOME_PATH_RE.fullmatch(path):
            score += 5
        elif _CO_CCR_DEPT_LIST_PATH_RE.fullmatch(path):
            score += 7
        elif _CO_CCR_AGENCY_LIST_PATH_RE.fullmatch(path):
            score += 8
        elif _CO_CCR_DOC_LIST_PATH_RE.fullmatch(path):
            score += 10
        elif _CO_CCR_DISPLAY_RULE_PATH_RE.fullmatch(path):
            action = str((query_params.get("action") or [""])[0]).strip().lower()
            rule_id = str((query_params.get("ruleId") or [""])[0]).strip()
            if action == "ruleinfo" and rule_id.isdigit():
                score += 12
        elif _CO_CCR_GENERATE_RULE_PDF_PATH_RE.fullmatch(path):
            rule_version_id = str((query_params.get("ruleVersionId") or [""])[0]).strip()
            if rule_version_id.isdigit():
                score += 14
        elif _CO_CCR_PDF_PATH_RE.fullmatch(path):
            rule_version_id = str((query_params.get("ruleVersionId") or [""])[0]).strip()
            if rule_version_id.isdigit():
                score += 14
    if host == "rules.sos.ga.gov":
        if normalized_path.lower() == "/gac":
            score += 6
        elif _GA_GAC_DEPARTMENT_PATH_RE.fullmatch(path):
            score += 7
        elif _GA_GAC_CHAPTER_PATH_RE.fullmatch(path):
            score += 8
        elif _GA_GAC_SUBJECT_PATH_RE.fullmatch(path):
            score += 9
        elif _GA_GAC_RULE_PATH_RE.fullmatch(path):
            score += 13
        elif normalized_path.lower() in {"/", "/help.aspx", "/download_pdf.aspx"}:
            score -= 3
    if host == "www.srca.nm.gov":
        if _NM_NMAC_TITLES_PATH_RE.fullmatch(path):
            score += 8
        elif _NM_NMAC_TITLE_PATH_RE.fullmatch(path):
            score += 9
        elif _NM_NMAC_CHAPTER_PATH_RE.fullmatch(path):
            score += 10
        elif normalized_path.lower() == "/nmac-home":
            score += 4
        elif normalized_path.lower() == "/nmac-home/explanation-of-the-new-mexico-administrative-code":
            score -= 5
        elif normalized_path.lower() == "/":
            score -= 4
    if host in {"legislature.nm.gov", "nmlegis.gov", "www.nmlegis.gov"} and normalized_path.lower() in {
        "/",
        "/rules",
        "/regulations",
        "/administrative-code",
        "/code-of-regulations",
        "/agency-rules",
        "/policies",
        "/departments",
    }:
        score -= 10
    if host == "akrules.elaws.us":
        if normalized_path.lower() == "/aac":
            score += 7
        elif _AK_AAC_TITLE_PATH_RE.fullmatch(path):
            score += 9
        elif _AK_AAC_CHAPTER_PATH_RE.fullmatch(path):
            score += 10
        elif _AK_AAC_SECTION_PATH_RE.fullmatch(path):
            score += 13
        elif _AK_BOOKVIEW_PATH_RE.fullmatch(path):
            score -= 4
    if host == "apps.azsos.gov" and _AZ_OFFICIAL_DOCUMENT_PATH_RE.search(path):
        score += 8
        az_match = re.search(r"/Title_(\d{2})/(\d+)-(\d+)\.(?:pdf|rtf)$", path, re.IGNORECASE)
        if az_match is not None:
            az_title_number = int(az_match.group(1))
            if az_title_number == 1:
                score -= 8
            else:
                score += 3
            if path.lower().endswith(".pdf"):
                score += 1
    if host in {"lexisnexis.com", "www.lexisnexis.com"} and _VT_LEXIS_TOC_PATH_RE.fullmatch(path):
        score -= 8
    if host == "advance.lexis.com" and _VT_LEXIS_DOC_PATH_RE.fullmatch(path):
        score -= 6
    if host == "govt.westlaw.com" and path.lower().startswith("/calregs/browse/home/california/californiacodeofregulations"):
        score += 6
    if host == "govt.westlaw.com" and normalized_path.lower() == "/calregs/index":
        score += 4
    if host == "govt.westlaw.com" and path.lower().startswith("/calregs/document/"):
        score += 10
    if host == "carules.elaws.us" and path.lower().startswith("/code/"):
        score += 5
    if host == "oal.ca.gov" and normalized_path.lower() in {"/publications", "/publications/ccr"}:
        score -= 6
    if host == "carules.elaws.us" and normalized_path.lower() == "/search/allcode":
        score -= 8
    if host in {"legislature.mt.gov", "www.legislature.mt.gov"} and normalized_path.lower() in {
        "/regulations",
        "/administrative-code",
        "/code-of-regulations",
    }:
        score -= 6
    if host == "rules.mt.gov":
        if re.search(r"^/browse/collections/[0-9a-fA-F-]+/policies/[0-9a-fA-F-]+$", path, re.IGNORECASE):
            score += 12
        elif re.search(r"^/browse/collections/[0-9a-fA-F-]+/sections/[0-9a-fA-F-]+$", path, re.IGNORECASE):
            score += 8
        elif re.fullmatch(r"/browse/collections/[0-9a-fA-F-]+", normalized_path, re.IGNORECASE):
            score += 5
        elif normalized_path.lower() in {"/browse/collections", "/search"}:
            score += 2
    if host in {"sosmt.gov", "www.sosmt.gov"} and "/arm" in normalized_path.lower():
        score += 2
    if host == "admincode.legislature.state.al.us" and normalized_path.lower() == "/administrative-code":
        alabama_number = _alabama_public_code_number_from_url(value)
        if _AL_RULE_NUMBER_RE.fullmatch(alabama_number):
            score += 14
        else:
            score += 10
    if host == "admincode.legislature.state.al.us" and normalized_path.lower().startswith("/administrative-code#"):
        score += 8
    if host == "admincode.legislature.state.al.us" and normalized_path.lower() in {"/", "/agency", "/search"}:
        score -= 4
    if host in {"www.sos.arkansas.gov", "sos.arkansas.gov"} and normalized_path.lower() == "/rules-regulations":
        score += 4
    if host == "sos-rules-reg.ark.org" and normalized_path.lower() in {"/rules/search", "/rules/search/new"}:
        score += 8
    if host == "sos-rules-reg.ark.org" and normalized_path.lower() == "/rules/text_search":
        score += 9
    if host == "sos-rules-reg.ark.org" and re.search(r"^/rules/(?:search/\d+|text_search/\w+/\d+)$", path, re.IGNORECASE):
        score += 10
    if host == "sos-rules-reg.ark.org" and re.search(r"^/rules/pdf/[\w.-]+\.pdf$", path, re.IGNORECASE):
        score += 12
    if host == "codeofarrules.arkansas.gov" and normalized_path.lower() == "/rules/search":
        score += 8
    if host == "codeofarrules.arkansas.gov" and normalized_path.lower() == "/rules/rule" and "leveltype=" in query.lower():
        arkansas_level = _arkansas_rule_level_from_url(url)
        if arkansas_level == "section":
            score += 16
        elif arkansas_level in {"part", "subpart"}:
            score += 8
        else:
            score += 5
    if host in {"legislature.ar.gov", "arkleg.state.ar.us", "www.arkleg.state.ar.us"} and normalized_path.lower() in {
        "/",
        "/rules",
        "/regulations",
        "/administrative-code",
        "/code-of-regulations",
        "/agency-rules",
        "/policies",
        "/departments",
    }:
        score -= 10
    if host in {"www.alabamaadministrativecode.state.al.us", "alabamaadministrativecode.state.al.us"} and normalized_path.lower() == "/":
        score -= 3
    if _is_new_hampshire_archived_rule_leaf_url(url):
        score += 12
    elif _NH_ARCHIVED_RULE_CHAPTER_URL_RE.search(str(url or "").strip()):
        score += 6
    if host == "web.archive.org" and "gc.nh.gov/rules/about_rules/listagencies.aspx" in value:
        score += 8
    if host == "web.archive.org" and value.rstrip("/").endswith("https://gc.nh.gov/rules"):
        score += 5
    if host in {"gencourt.state.nh.us", "www.gencourt.state.nh.us"} and re.search(
        r"^/rules/state_agencies/[\w.-]+\.html$",
        path,
        re.IGNORECASE,
    ):
        score += 10
    if host == "legislature.nh.gov" and normalized_path.lower() in {"/regulations", "/administrative-code", "/code-of-regulations"}:
        score -= 5
    if host == "rules.ok.gov" and normalized_path.lower() == "/code":
        query_params = parse_qs(parsed.query or "")
        title_num = str((query_params.get("titleNum") or [""])[0]).strip()
        section_num = str((query_params.get("sectionNum") or [""])[0]).strip()
        if title_num and _OK_RULE_SECTION_NUM_RE.fullmatch(section_num):
            score += 13
        elif title_num:
            score += 6
        else:
            score += 4
    if host == "legislature.ok.gov" and _OK_NON_SUBSTANTIVE_LEGISLATURE_PATH_RE.fullmatch(path):
        score -= 8
    if host in {"lexisnexis.com", "www.lexisnexis.com"} and _VT_LEXIS_TOC_PATH_RE.fullmatch(path):
        score -= 8
    if host == "advance.lexis.com":
        if _VT_LEXIS_DOC_PATH_RE.fullmatch(path):
            score -= 6
        elif normalized_path.lower() == "/container":
            score -= 4
    if host == "secure.vermont.gov" and normalized_path.lower() == "/sos/rules/display.php" and re.search(r"(?:^|[?&])r=\d+", parsed.query or "", re.IGNORECASE):
        score += 18
    if host == "texas-sos.appianportalsgov.com" and normalized_path.lower() == "/rules-and-meetings":
        query_params = parse_qs(parsed.query or "")
        interface = str((query_params.get("interface") or [""])[0]).strip().upper()
        record_id = str((query_params.get("recordId") or [""])[0]).strip()
        if interface == "VIEW_TAC_SUMMARY" and record_id.isdigit():
            score += 13
        elif interface == "VIEW_TAC":
            if str((query_params.get("subchapter") or [""])[0]).strip() and str((query_params.get("chapter") or [""])[0]).strip():
                score += 10
            elif str((query_params.get("chapter") or [""])[0]).strip() and str((query_params.get("part") or [""])[0]).strip():
                score += 8
            elif str((query_params.get("part") or [""])[0]).strip() and str((query_params.get("title") or [""])[0]).strip():
                score += 7
            elif str((query_params.get("title") or [""])[0]).strip():
                score += 6
            else:
                score += 5
    if host == "www.sos.state.tx.us" and _TX_TRANSFER_PATH_RE.search(path):
        score -= 8
    if host == "secure.vermont.gov" and normalized_path.lower() in {"/sos/rules", "/sos/rules/index.php"}:
        score += 4
    if host == "secure.vermont.gov" and normalized_path.lower() in {
        "/sos/rules/search.php",
        "/sos/rules/rssfeed.php",
        "/sos/rules/calendar.php",
        "/sos/rules/subscribe.php",
        "/sos/rules/contact.php",
        "/sos/rules/icalendar.php",
    }:
        score -= 3
    if host in {"legislature.vt.gov", "legislature.vermont.gov"} and normalized_path.lower() in {
        "/",
        "/rules",
        "/regulations",
        "/administrative-code",
        "/code-of-regulations",
        "/agency-rules",
        "/policies",
    }:
        score -= 6
    if host == "sdlegislature.gov" and _SD_RULE_INDEX_PATH_RE.fullmatch(path):
        score += 5
    if host == "sdlegislature.gov" and _SD_RULE_DETAIL_PATH_RE.fullmatch(path):
        score += 11
    if host == "sdlegislature.gov" and _SD_DISPLAY_RULE_PATH_RE.search(path):
        rule_value = str((parse_qs(query).get("Rule") or [""])[0]).strip()
        if _SD_RULE_REFERENCE_RE.fullmatch(rule_value):
            score += 12
    if host == "sharetngov.tnsosfiles.com" and normalized_path.lower() in {
        "/sos/rules/index.htm",
        "/sos/pub/tar/index.htm",
        "/sos/rules/rules2.htm",
        "/sos/rules/rules_list.shtml",
        "/sos/rules/effectives/effectives.htm",
        "/sos/rules/tenncare.htm",
    }:
        score += 9
    if host == "sharetngov.tnsosfiles.com" and re.search(r"^/sos/rules/\d{4}/\d{4}\.htm$", path, re.IGNORECASE):
        score += 12
    if host == "sharetngov.tnsosfiles.com" and re.search(r"^/sos/rules/\d{4}/[\d-]+/[\d-]+\.htm$", path, re.IGNORECASE):
        score += 9
    if host == "sharetngov.tnsosfiles.com" and re.search(r"^/sos/rules/\d{4}/[\w.-]+\.pdf$", path, re.IGNORECASE):
        score += 10
    if host == "sharetngov.tnsosfiles.com" and re.search(r"^/sos/rules/\d{4}/[\d-]+/[\w.-]+\.pdf$", path, re.IGNORECASE):
        score += 10
    if host == "sharetngov.tnsosfiles.com" and re.search(r"^/sos/rules_filings/[\w.-]+\.pdf$", path, re.IGNORECASE):
        score += 8
    if host == "ars.apps.lara.state.mi.us" and normalized_path.lower() == "/admincode/deptbureauadmincode":
        score += 8
    if host == "ars.apps.lara.state.mi.us" and normalized_path.lower() == "/transaction/rfrtransaction":
        score += 9
    if host == "ars.apps.lara.state.mi.us" and normalized_path.lower() == "/admincode/downloadadmincodefile":
        query_lower = query.lower()
        if "returnhtml=true" in query_lower:
            score += 12
    if host == "ars.apps.lara.state.mi.us" and normalized_path.lower() == "/transaction/downloadfile":
        query_lower = query.lower()
        if "returnhtml=true" in query_lower and "filetype=finalrule" in query_lower:
            score += 12
    if host == "rules.wyo.gov" and normalized_path.lower() == "/search.aspx":
        mode = str((parse_qs(query).get("mode") or [""])[0]).strip()
        if mode == "7":
            score += 9
        else:
            score += 4
    if host == "rules.wyo.gov" and normalized_path.lower() == "/agencies.aspx":
        score += 5
    if host == "rules.wyo.gov" and normalized_path.lower() == "/help/public/wyoming-administrative-rules-h.html":
        score += 5
    if host == "rules.wyo.gov" and normalized_path.lower() == "/ajaxhandler.ashx":
        handler = str((parse_qs(query).get("handler") or [""])[0]).strip().lower()
        if handler == "search_getprogramrules":
            score += 10
        elif handler == "getruleversionhtml":
            score += 12
    if host == "publications.tnsosfiles.com" and normalized_path.lower() in {"/rules", "/rules/"}:
        score += 6
    if host == "sos.tn.gov" and normalized_path.lower() in {
        "/publications/services/administrative-register",
        "/publications/services/effective-rules-and-regulations-of-the-state-of-tennessee",
    }:
        score -= 2
    if host in {"www.tn.gov", "tn.gov"} and normalized_path.lower() in {
        "/sos/rules-and-regulations.html",
        "/tga",
    }:
        score -= 8
    if host == "legislature.tn.gov" and normalized_path.lower() in {
        "/",
        "/rules",
        "/regulations",
        "/administrative-code",
        "/code-of-regulations",
        "/agency-rules",
        "/policies",
        "/departments",
    }:
        score -= 10
    if host in {"www.wyoleg.gov", "wyoleg.gov", "legislature.wy.gov"} and normalized_path.lower() in {
        "/",
        "/rules",
        "/regulations",
        "/administrative-code",
        "/code-of-regulations",
        "/agency-rules",
        "/policies",
        "/departments",
        "/statestatutes/statutesdownload",
    }:
        score -= 10
    if host == "www.ilga.gov" and normalized_path.lower() == "/agencies/jcar/admincode":
        score += 6
    if host == "www.ilga.gov" and normalized_path.lower() == "/agencies/jcar/parts":
        score += 7
    if host == "www.ilga.gov" and normalized_path.lower() == "/agencies/jcar/sections":
        score += 9
    if host == "www.ilga.gov" and normalized_path.lower() == "/agencies/jcar/entirepart":
        score += 11
    if host == "www.ilga.gov" and re.search(r"^/commission/jcar/admincode/\d+/[\w.-]+\.html$", path, re.IGNORECASE):
        score += 12
    if host == "www.ilga.gov" and normalized_path.lower() == "/commission/jcar/admincode":
        score += 5
    if host == "iar.iga.in.gov" and normalized_path.lower() in {"/code", "/code/current", "/code/2006", "/code/2024"}:
        score += 9
    if host == "iar.iga.in.gov" and re.search(r"^/code/(?:current|2006|2024)/\d+(?:/\d+(?:\.\d+)?)", path, re.IGNORECASE):
        score += 11
    if host == "legislature.in.gov" and _IN_NON_RULE_LEGISLATURE_PATH_RE.fullmatch(normalized_path):
        score -= 8
    if host in {"www.mass.gov", "mass.gov"} and _MA_CMR_INVENTORY_PATH_RE.search(normalized_path):
        score += 7
    if host in {"www.mass.gov", "mass.gov"} and _MA_CMR_DETAIL_PATH_RE.search(path):
        score += 12
    if host == "regs.maryland.gov" and _MD_COMAR_INVENTORY_PATH_RE.search(normalized_path):
        score += 7
    if host == "regs.maryland.gov" and _MD_COMAR_DETAIL_PATH_RE.search(path):
        score += 12
        if (path.rstrip("/").split("/")[-1].count(".") if path else 0) >= 3:
            score += 3
    if host in {"www.maine.gov", "maine.gov"} and _ME_RULES_INDEX_PATH_RE.search(normalized_path):
        score += 6
    if host in {"www.maine.gov", "maine.gov"} and _ME_RULE_DOCUMENT_PATH_RE.search(path):
        score += 12
    if host == "www.revisor.mn.gov" and _MN_RULE_INDEX_PATH_RE.search(normalized_path):
        score += 8
    if host == "www.revisor.mn.gov" and _MN_RULE_AGENCY_PATH_RE.search(normalized_path):
        score += 9
    if host == "www.revisor.mn.gov" and _MN_RULE_DETAIL_PATH_RE.search(path):
        score += 13
    if host == "www.sos.mo.gov" and _MO_CSR_INDEX_PATH_RE.search(normalized_path):
        score += 8
    if host == "www.sos.mo.gov" and _MO_CSR_TITLE_PATH_RE.search(normalized_path):
        score += 10
    if host == "www.sos.mo.gov" and _MO_CSR_PDF_PATH_RE.search(path):
        score += 13
    if host == "rules.nebraska.gov":
        if normalized_path.lower() == "/":
            score += 5
        elif normalized_path.lower() == "/browse-rules":
            score += 9
        elif normalized_path.lower() == "/rules":
            query_params = parse_qs(parsed.query or "")
            agency_id = str((query_params.get("agencyId") or [""])[0]).strip()
            title_id = str((query_params.get("titleId") or [""])[0]).strip()
            if agency_id.isdigit() and title_id.isdigit():
                score += 11
            else:
                score += 7
        elif _NE_RULE_FILESTORAGE_PDF_PATH_RE.search(path):
            score += 14
    if host == "www.sec.state.ma.us" and normalized_path.lower() == "/divisions/pubs-regs/about-cmr.htm":
        score += 6
    if host in {"malegislature.gov", "www.malegislature.gov", "legislature.ma.gov"} and _MA_GENERAL_LAWS_PATH_RE.search(path):
        score -= 10
    return score


def _url_key(url: str) -> str:
    normalized_url = urldefrag(str(url or "").strip()).url
    parsed = urlparse(normalized_url)
    if parsed.netloc.lower() == "adminrules.utah.gov":
        normalized_path = re.sub(r"(?i)\+(rules)(?=$|[/?#])", r"%20\1", parsed.path or "")
        normalized_url = parsed._replace(path=normalized_path).geturl()
    return normalized_url.lower().rstrip("/")


def _arizona_official_document_group_key(url: str) -> str:
    parsed = urlparse(urldefrag(str(url or "").strip()).url)
    if parsed.netloc.lower() != "apps.azsos.gov":
        return ""
    path = parsed.path or ""
    if not _AZ_OFFICIAL_DOCUMENT_PATH_RE.search(path):
        return ""
    return re.sub(r"(?i)\.(?:pdf|rtf)$", "", path).lower()


def _arizona_official_document_title_family_key(url: str) -> str:
    parsed = urlparse(urldefrag(str(url or "").strip()).url)
    if parsed.netloc.lower() != "apps.azsos.gov":
        return ""
    match = re.match(r"(?i)^/public_services/(title_\d+)/", parsed.path or "")
    if not match:
        return ""
    return match.group(1).lower()


def _should_prefer_arizona_official_document_url(candidate_url: str, existing_url: str) -> bool:
    candidate_group_key = _arizona_official_document_group_key(candidate_url)
    existing_group_key = _arizona_official_document_group_key(existing_url)
    if not candidate_group_key or candidate_group_key != existing_group_key:
        return False
    return _is_rtf_candidate_url(candidate_url) and _is_pdf_candidate_url(existing_url)


def _gap_summary_host_key(host: str) -> str:
    raw_value = str(host or "").strip()
    if not raw_value:
        return ""

    parsed = urlparse(raw_value if "://" in raw_value or raw_value.startswith("//") else f"//{raw_value}")
    value = str(parsed.netloc or raw_value).strip().lower().strip(".")
    normalized_path = (parsed.path or "/").rstrip("/") or "/"

    if value in {"apps.azsos.gov", "www.azsos.gov"}:
        return "azsos.gov"
    if value in {"adminrules.utah.gov", "rules.utah.gov", "le.utah.gov", "legislature.ut.gov"}:
        return "adminrules.utah.gov"
    if value in {"rules.sos.ri.gov", "sos.ri.gov", "www.sos.ri.gov", "legislature.ri.gov", "webserver.rilin.state.ri.us"}:
        return "rules.sos.ri.gov"
    if value in {
        "mass.gov",
        "www.mass.gov",
        "sec.state.ma.us",
        "www.sec.state.ma.us",
        "legislature.ma.gov",
        "malegislature.gov",
        "www.malegislature.gov",
    }:
        return "mass.gov"
    if value == "oal.ca.gov" and normalized_path in {"/publications", "/publications/ccr"}:
        return "govt.westlaw.com"
    if value == "carules.elaws.us" and normalized_path == "/search/allcode":
        return "govt.westlaw.com"
    if value.startswith("www."):
        return value[4:]
    return value


def _score_candidate_link(link_url: str, link_text: str = "", page_url: str = "") -> int:
    score = _score_candidate_url(link_url)
    hay = " ".join([str(link_text or ""), str(link_url or "")])
    if re.search(r"\b(?:title|chapter|article|part|section|subchapter)\b", hay, re.IGNORECASE):
        score += 2
    if re.search(r"\b(?:r\d{1,3}-\d+|\d{1,3}\.\d{1,3}(?:\.\d{1,4})?)\b", hay, re.IGNORECASE):
        score += 2
    lower_url = str(link_url or "").lower()
    if "adminrules.utah.gov/public/search" in lower_url:
        score += 3
        if any(token in lower_url for token in ("current%20rules", "/proposed", "/emergency")):
            score += 1
    parsed = urlparse(str(link_url or "").strip())
    host = parsed.netloc.lower()
    path = parsed.path or ""
    if host == "adminrules.utah.gov" and _UT_RULE_DETAIL_PATH_RE.search(path):
        score += 8
    if host == "rules.utah.gov" and _UT_NON_RULE_NEWS_PATH_RE.search(path):
        score -= 6
    if host == "apps.azsos.gov" and _AZ_OFFICIAL_DOCUMENT_PATH_RE.search(path):
        score += 8
    if host in {"lexisnexis.com", "www.lexisnexis.com"} and _VT_LEXIS_TOC_PATH_RE.fullmatch(path):
        if re.search(r"code\s+of\s+vermont\s+rules", hay, re.IGNORECASE):
            score += 8
    if host == "advance.lexis.com" and _VT_LEXIS_DOC_PATH_RE.fullmatch(path):
        score += 10
    if host == "secure.vermont.gov" and path.lower() == "/sos/rules/display.php":
        if re.search(r"(?:^|[?&])r=\d+", parsed.query or "", re.IGNORECASE):
            score += 2
    if host == "govt.westlaw.com" and path.lower().startswith("/calregs/document/"):
        score += 12
    if host == "govt.westlaw.com" and path.lower().startswith("/calregs/browse/home/california/californiacodeofregulations"):
        if re.search(r"\barticle\b", hay, re.IGNORECASE):
            score += 8
        elif re.search(r"\bchapter\b", hay, re.IGNORECASE):
            score += 6
        elif re.search(r"\bdivision\b", hay, re.IGNORECASE):
            score += 4
        elif re.search(r"\btitle\b", hay, re.IGNORECASE):
            score += 2
    if re.search(r"/code/(?:current|2006)/\d+/\d+(?:\.\d+)?", lower_url):
        score += 4
        if re.search(r"\b(?:article|rule)\b", hay, re.IGNORECASE):
            score += 2
    if host == "www.ilga.gov" and path.lower() == "/agencies/jcar/parts":
        score += 5
    if host == "www.ilga.gov" and path.lower() == "/agencies/jcar/sections":
        score += 8
    if host == "www.ilga.gov" and path.lower() == "/agencies/jcar/entirepart":
        score += 10
    if host == "www.ilga.gov" and re.search(r"^/commission/jcar/admincode/\d+/[\w.-]+\.html$", path, re.IGNORECASE):
        score += 11
    if host == "www.ilga.gov" and re.search(r"\bsection\s+\d+\.\d+\b", hay, re.IGNORECASE):
        score += 4
    if host in {"www.mass.gov", "mass.gov"} and _MA_CMR_INVENTORY_PATH_RE.search(path):
        score += 5
    if host in {"www.mass.gov", "mass.gov"} and _MA_CMR_DETAIL_PATH_RE.search(path):
        score += 10
        if re.search(r"\b\d{3}\s+cmr\b", hay, re.IGNORECASE):
            score += 3
    if host == "regs.maryland.gov" and _MD_COMAR_INVENTORY_PATH_RE.search(path):
        score += 5
    if host == "regs.maryland.gov" and _MD_COMAR_DETAIL_PATH_RE.search(path):
        score += 10
        if re.search(r"\b(?:comar|title|subtitle|chapter|regulation)\b", hay, re.IGNORECASE):
            score += 2
        if (path.rstrip("/").split("/")[-1].count(".") if path else 0) >= 3:
            score += 3
    if host in {"www.maine.gov", "maine.gov"} and _ME_RULES_INDEX_PATH_RE.search(path):
        score += 4
    if host in {"www.maine.gov", "maine.gov"} and _ME_RULE_DOCUMENT_PATH_RE.search(path):
        score += 10
        if re.search(r"\b(?:ch\.?|chapter|section|appendix|manual|rule)\b", hay, re.IGNORECASE):
            score += 2
    if host == "www.revisor.mn.gov" and _MN_RULE_INDEX_PATH_RE.search(path):
        score += 6
    if host == "www.revisor.mn.gov" and _MN_RULE_AGENCY_PATH_RE.search(path):
        score += 8
    if host == "www.revisor.mn.gov" and _MN_RULE_DETAIL_PATH_RE.search(path):
        score += 12
        if re.search(r"\b(?:chapter|part|rule|administrative)\b", hay, re.IGNORECASE):
            score += 2
    if host == "www.sos.mo.gov" and _MO_CSR_INDEX_PATH_RE.search(path):
        score += 6
    if host == "www.sos.mo.gov" and _MO_CSR_TITLE_PATH_RE.search(path):
        score += 9
        if re.search(r"\b(?:title|division|chapter|code of state regulations)\b", hay, re.IGNORECASE):
            score += 2
    if host == "www.sos.mo.gov" and _MO_CSR_PDF_PATH_RE.search(path):
        score += 12
        if re.search(r"\b(?:chapter|rule|authority|code of state regulations)\b", hay, re.IGNORECASE):
            score += 2
    if host == "rules.nebraska.gov":
        if normalized_path.lower() == "/browse-rules":
            score += 8
        elif normalized_path.lower() == "/rules":
            query_params = parse_qs(parsed.query or "")
            agency_id = str((query_params.get("agencyId") or [""])[0]).strip()
            title_id = str((query_params.get("titleId") or [""])[0]).strip()
            if agency_id.isdigit() and title_id.isdigit():
                score += 10
        elif _NE_RULE_FILESTORAGE_PDF_PATH_RE.search(path):
            score += 12
            if re.search(r"\b(?:chapter|rule|effective date|title)\b", hay, re.IGNORECASE):
                score += 2
    if host == "sdlegislature.gov" and _SD_RULE_DETAIL_PATH_RE.fullmatch(path):
        score += 10
    if host == "sdlegislature.gov" and _SD_DISPLAY_RULE_PATH_RE.search(path):
        rule_value = str((parse_qs(parsed.query or "").get("Rule") or [""])[0]).strip()
        if _SD_RULE_REFERENCE_RE.fullmatch(rule_value):
            score += 10
    if host in {"malegislature.gov", "www.malegislature.gov", "legislature.ma.gov"} and _MA_GENERAL_LAWS_PATH_RE.search(path):
        score -= 10

    low_text = str(link_text or "").strip()
    if low_text and _LOW_VALUE_LINK_TEXT_RE.fullmatch(low_text):
        score -= 4
    if _LOW_VALUE_LINK_URL_RE.search(str(link_url or "")):
        score -= 4
    if page_url and _url_key(link_url) == _url_key(page_url):
        score -= 5
    return score


def _candidate_montana_policy_urls_from_html(*, html: str, url: str, limit: int = 24) -> List[str]:
    body = str(html or "")
    url_value = str(url or "").strip()
    parsed = urlparse(url_value)
    if parsed.netloc.lower() != "rules.mt.gov" or "/browse/collections/" not in (parsed.path or ""):
        return []

    out: List[str] = []
    seen: set[str] = set()
    limit_n = max(1, int(limit))
    for href in re.findall(r'href=["\']([^"\']+)["\']', body, re.IGNORECASE):
        candidate = urljoin(url_value, href.strip())
        candidate_parsed = urlparse(candidate)
        if candidate_parsed.netloc.lower() != "rules.mt.gov":
            continue
        if not re.search(
            r"^/browse/collections/[0-9a-fA-F-]+/policies/[0-9a-fA-F-]+$",
            candidate_parsed.path,
            re.IGNORECASE,
        ):
            continue
        normalized = candidate_parsed.geturl()
        if normalized in seen:
            continue
        seen.add(normalized)
        out.append(normalized)
        if len(out) >= limit_n:
            break
    return out


def _build_initial_pending_candidates(
    ranked_urls: List[tuple[str, int]],
    seed_expansion_candidates: List[tuple[str, int]],
    max_candidates: int,
) -> List[tuple[str, int]]:
    pending_by_key: Dict[str, tuple[str, int]] = {}
    pending: List[tuple[str, int]] = []

    for url, score in [*ranked_urls[: max(1, int(max_candidates))], *seed_expansion_candidates]:
        key = _url_key(url)
        if not key:
            continue
        existing = pending_by_key.get(key)
        if existing is None or int(score) > int(existing[1]):
            pending_by_key[key] = (url, int(score))

    pending.extend(pending_by_key.values())
    pending.sort(key=_pending_candidate_sort_key)
    return pending


def _pending_candidate_sort_key(item: tuple[str, int]) -> tuple[int, int, int, str]:
    url, score = item
    return (
        -int(score),
        -int(_is_immediate_direct_detail_candidate_url(url)),
        -_seed_prefetch_priority(url),
        _url_key(url) or str(url or "").strip().lower(),
    )


def _seed_expansion_backlog_is_ready(seed_expansion_candidates: List[tuple[str, int]], max_fetch: int) -> bool:
    if not seed_expansion_candidates:
        return False
    unique_keys = {
        _url_key(url)
        for url, score in seed_expansion_candidates
        if _url_key(url) and int(score) > 0
    }
    if not unique_keys:
        return False
    # Small bounded runs should not need a huge seed-expansion backlog before
    # we start prioritizing concrete detail candidates over broad search/index
    # surfaces. Keep the floor above trivial noise, but scale more gently.
    threshold = max(3, min(8, max(1, int(max_fetch)) * 2))
    return len(unique_keys) >= threshold


def _state_seed_expansion_backlog_is_ready(
    *,
    state_code: str,
    seed_expansion_candidates: List[tuple[str, int]],
    max_fetch: int,
) -> bool:
    if _seed_expansion_backlog_is_ready(seed_expansion_candidates, max_fetch):
        return True
    if state_code != "CA":
        return False
    california_detail_keys = {
        _url_key(url)
        for url, score in seed_expansion_candidates
        if _url_key(url)
        and int(score) > 0
        and _is_direct_detail_candidate_url(url)
        and urlparse(str(url or "").strip()).netloc.lower() == "govt.westlaw.com"
        and (urlparse(str(url or "").strip()).path or "").lower().startswith("/calregs/document/")
    }
    return len(california_detail_keys) >= min(2, max(1, int(max_fetch)))


def _is_direct_detail_candidate_url(url: str) -> bool:
    parsed = urlparse(str(url or "").strip())
    host = parsed.netloc.lower()
    path = parsed.path or ""
    normalized_path = path.rstrip("/") or "/"
    if host == "admincode.legislature.state.al.us" and normalized_path.lower() == "/administrative-code":
        return bool(_AL_RULE_NUMBER_RE.fullmatch(_alabama_public_code_number_from_url(url)))
    if host == "eregulations.ct.gov" and _CT_EREGS_SECTION_PATH_RE.fullmatch(path):
        return True
    if host in {"www.sos.state.co.us", "www.coloradosos.gov"}:
        query_params = parse_qs(parsed.query or "")
        if _CO_CCR_GENERATE_RULE_PDF_PATH_RE.fullmatch(path):
            rule_version_id = str((query_params.get("ruleVersionId") or [""])[0]).strip()
            if rule_version_id.isdigit():
                return True
        if _CO_CCR_PDF_PATH_RE.fullmatch(path):
            rule_version_id = str((query_params.get("ruleVersionId") or [""])[0]).strip()
            if rule_version_id.isdigit():
                return True
    if _is_new_hampshire_archived_rule_leaf_url(url):
        return True
    if host in {"gencourt.state.nh.us", "www.gencourt.state.nh.us"} and re.search(
        r"^/rules/state_agencies/[\w.-]+\.html$",
        path,
        re.IGNORECASE,
    ):
        return True
    if host == "advance.lexis.com" and _VT_LEXIS_DOC_PATH_RE.fullmatch(path):
        return True
    if host == "secure.vermont.gov" and normalized_path.lower() == "/sos/rules/display.php":
        if re.search(r"(?:^|[?&])r=\d+", parsed.query or "", re.IGNORECASE):
            return True
    if host == "rules.ok.gov" and normalized_path.lower() == "/code":
        query_params = parse_qs(parsed.query or "")
        title_num = str((query_params.get("titleNum") or [""])[0]).strip()
        section_num = str((query_params.get("sectionNum") or [""])[0]).strip()
        if title_num and (not section_num or _OK_RULE_SECTION_NUM_RE.fullmatch(section_num)):
            return True
    if host == "texas-sos.appianportalsgov.com" and normalized_path.lower() == "/rules-and-meetings":
        query_params = parse_qs(parsed.query or "")
        interface = str((query_params.get("interface") or [""])[0]).strip().upper()
        record_id = str((query_params.get("recordId") or [""])[0]).strip()
        if interface == "VIEW_TAC_SUMMARY" and record_id.isdigit():
            return True
    if host == "sharetngov.tnsosfiles.com" and re.search(r"^/sos/rules/\d{4}/\d{4}\.htm$", path, re.IGNORECASE):
        return True
    if host == "sharetngov.tnsosfiles.com" and re.search(r"^/sos/rules/\d{4}/[\w.-]+\.pdf$", path, re.IGNORECASE):
        return True
    if host == "sharetngov.tnsosfiles.com" and re.search(r"^/sos/rules/\d{4}/[\d-]+/[\w.-]+\.pdf$", path, re.IGNORECASE):
        return True
    if host == "rules.mt.gov" and re.search(
        r"^/browse/collections/[0-9a-fA-F-]+/policies/[0-9a-fA-F-]+$",
        path,
        re.IGNORECASE,
    ):
        return True
    if host == "rules.wyo.gov" and normalized_path.lower() == "/ajaxhandler.ashx":
        handler = str((parse_qs(parsed.query or "").get("handler") or [""])[0]).strip().lower()
        if handler == "getruleversionhtml":
            return True
    if host == "rules.sos.ri.gov" and _RI_RICR_DETAIL_PATH_RE.fullmatch(path):
        return True
    if host == "adminrules.utah.gov" and _UT_RULE_DETAIL_PATH_RE.search(path):
        return True
    if host == "apps.azsos.gov" and _AZ_OFFICIAL_DOCUMENT_PATH_RE.search(path):
        return True
    if host in {"azsos.gov", "www.azsos.gov"} and normalized_path.lower() == "/rules/arizona-administrative-code":
        return True
    if host == "www.sos.ms.gov" and re.search(r"^/adminsearch/ACCode/[\w.-]+\.pdf$", path, re.IGNORECASE):
        return True
    if host == "iar.iga.in.gov" and re.search(r"/code/(?:current|2006|2024)/\d+/\d+(?:\.\d+)?(?:/\d+(?:\.\d+)?)?", path, re.IGNORECASE):
        return True
    if host == "akrules.elaws.us" and _AK_AAC_SECTION_PATH_RE.fullmatch(path):
        return True
    if host == "www.akleg.gov" and normalized_path.lower() == "/basis/aac.asp":
        query_params = parse_qs(parsed.query or "")
        sec_start = str((query_params.get("secStart") or [""])[0]).strip()
        sec_end = str((query_params.get("secEnd") or [""])[0]).strip()
        media = str((query_params.get("media") or [""])[0]).strip().lower()
        if media == "print" and sec_start == sec_end and _AK_AAC_SECTION_PATH_RE.fullmatch(f"/aac/{sec_start}"):
            return True
    if host == "rules.sos.ga.gov" and _GA_GAC_RULE_PATH_RE.fullmatch(path):
        return True
    if host == "sdlegislature.gov" and _SD_RULE_DETAIL_PATH_RE.fullmatch(path):
        return True
    if host == "sdlegislature.gov" and _SD_DISPLAY_RULE_PATH_RE.search(path):
        rule_value = str((parse_qs(parsed.query or "").get("Rule") or [""])[0]).strip()
        if _SD_RULE_REFERENCE_RE.fullmatch(rule_value):
            return True
    if host == "ars.apps.lara.state.mi.us" and normalized_path.lower() == "/admincode/downloadadmincodefile":
        query_lower = (parsed.query or "").lower()
        if "returnhtml=true" in query_lower:
            return True
    if host == "ars.apps.lara.state.mi.us" and normalized_path.lower() == "/transaction/downloadfile":
        query_lower = (parsed.query or "").lower()
        if "returnhtml=true" in query_lower and "filetype=finalrule" in query_lower:
            return True
    if host == "www.ilga.gov" and path.lower() == "/agencies/jcar/entirepart":
        return True
    if host == "www.ilga.gov" and re.search(r"^/commission/jcar/admincode/\d+/[\w.-]+\.html$", path, re.IGNORECASE):
        return True
    if host == "www.sos.ks.gov" and normalized_path.lower() == "/publications/pubs_kar_regs.aspx":
        kar_value = str((parse_qs(parsed.query or "").get("KAR") or [""])[0]).strip()
        if re.fullmatch(r"\d{1,3}-\d{1,3}-\d+[A-Za-z-]*", kar_value):
            return True
    if host == "govt.westlaw.com" and normalized_path.lower().startswith("/calregs/document/"):
        return True
    if host in {"www.mass.gov", "mass.gov"} and _MA_CMR_DETAIL_PATH_RE.search(path):
        return True
    if host == "regs.maryland.gov" and _MD_COMAR_DETAIL_PATH_RE.search(path):
        return True
    if host in {"www.maine.gov", "maine.gov"} and _ME_RULE_DOCUMENT_PATH_RE.search(path):
        return True
    if host == "www.revisor.mn.gov" and _MN_RULE_DETAIL_PATH_RE.search(path):
        return True
    if host == "www.sos.mo.gov" and _MO_CSR_PDF_PATH_RE.search(path):
        return True
    if host == "rules.nebraska.gov" and _NE_RULE_FILESTORAGE_PDF_PATH_RE.search(path):
        return True
    if host == "codeofarrules.arkansas.gov" and path.lower() == "/rules/rule":
        if _arkansas_rule_level_from_url(url) == "section":
            return True
    return False


def _is_immediate_direct_detail_candidate_url(url: str) -> bool:
    if not _is_direct_detail_candidate_url(url):
        return False
    parsed = urlparse(str(url or "").strip())
    host = parsed.netloc.lower()
    normalized_path = (parsed.path or "").rstrip("/") or "/"
    if host in {"azsos.gov", "www.azsos.gov"} and normalized_path.lower() == "/rules/arizona-administrative-code":
        return False
    if host == "admincode.legislature.state.al.us" and normalized_path.lower() == "/administrative-code":
        return bool(_AL_RULE_NUMBER_RE.fullmatch(_alabama_public_code_number_from_url(url)))
    return True


def _is_arizona_official_pdf_url(url: str) -> bool:
    parsed = urlparse(str(url or "").strip())
    return (
        parsed.netloc.lower() == "apps.azsos.gov"
        and _AZ_OFFICIAL_DOCUMENT_PATH_RE.search(parsed.path or "") is not None
        and _is_pdf_candidate_url(url)
    )


def _direct_detail_candidate_backlog_is_ready(candidate_urls: List[str], max_fetch: int) -> bool:
    detail_candidates = [
        (url, _score_candidate_url(url))
        for url in candidate_urls
        if _is_immediate_direct_detail_candidate_url(url)
    ]
    return _seed_expansion_backlog_is_ready(detail_candidates, max_fetch)


def _seed_prefetch_priority(url: str) -> int:
    score = _score_candidate_url(url)
    parsed = urlparse(str(url or "").strip())
    host = parsed.netloc.lower()
    path = (parsed.path or "").lower()

    if _is_direct_detail_candidate_url(url):
        score += 12
        if _is_rtf_candidate_url(url):
            score += 4
        if host == "apps.azsos.gov" and _AZ_OFFICIAL_DOCUMENT_PATH_RE.search(parsed.path or ""):
            if _is_pdf_candidate_url(url):
                score += 8
            elif _is_rtf_candidate_url(url):
                score -= 2

    if host == "apps.azsos.gov" and path in {"/public_services/codetoc.htm", "/public_services/index/"}:
        score += 10

    if _OFFICIAL_RULE_INDEX_URL_RE.search(str(url or "")):
        score += 4

    return score


def _prioritized_direct_detail_urls_from_candidates(
    candidates: List[tuple[str, int]],
    *,
    limit: int,
    exclude_urls: Optional[set[str]] = None,
) -> List[str]:
    prioritized: List[str] = []
    seen: set[str] = set()
    excluded = {_url_key(url) for url in (exclude_urls or set()) if _url_key(url)}

    def _append_prioritized_url(candidate_url: str) -> bool:
        key = _url_key(candidate_url)
        if not key or key in seen or key in excluded:
            return False
        seen.add(key)
        prioritized.append(candidate_url)
        return True

    for candidate_url, score in candidates:
        if int(score) <= 0:
            continue
        parsed = urlparse(str(candidate_url or "").strip())
        normalized_path = (parsed.path or "").rstrip("/") or "/"
        if parsed.netloc.lower() in {"azsos.gov", "www.azsos.gov"} and normalized_path.lower() == "/rules/arizona-administrative-code":
            _append_prioritized_url(candidate_url)
            if len(prioritized) >= max(1, int(limit)):
                return prioritized

    for url, score in sorted(
        candidates,
        key=lambda item: (
            2 if _is_arizona_official_pdf_url(item[0]) else 1 if _is_rtf_candidate_url(item[0]) else 0,
            int(item[1]),
        ),
        reverse=True,
    ):
        if int(score) <= 0:
            continue
        if not _is_direct_detail_candidate_url(url):
            continue
        if _is_pdf_candidate_url(url):
            parsed = urlparse(url)
            if parsed.netloc.lower() == "apps.azsos.gov" and _AZ_OFFICIAL_DOCUMENT_PATH_RE.search(parsed.path or ""):
                rtf_sibling_url = re.sub(r"(?i)\.pdf(?=$|\?)", ".rtf", url)
                _append_prioritized_url(url)
                if len(prioritized) >= max(1, int(limit)):
                    break
                if rtf_sibling_url != url:
                    _append_prioritized_url(rtf_sibling_url)
                    if len(prioritized) >= max(1, int(limit)):
                        break
                continue
        _append_prioritized_url(url)
        if len(prioritized) >= max(1, int(limit)):
            break

    return prioritized


def _prioritized_arizona_late_retry_urls(
    candidate_urls: List[str],
    *,
    limit: int,
    extra_preferred_urls: Optional[List[str]] = None,
    exclude_urls: Optional[set[str]] = None,
) -> List[str]:
    prioritized: List[str] = []
    seen: set[str] = set()
    excluded = {_url_key(url) for url in (exclude_urls or set()) if _url_key(url)}
    excluded_group_keys = {
        group_key
        for group_key in (_arizona_official_document_group_key(url) for url in (exclude_urls or set()))
        if group_key
    }

    def _append(candidate_url: str) -> bool:
        key = _url_key(candidate_url)
        group_key = _arizona_official_document_group_key(candidate_url)
        if not key or key in excluded or key in seen:
            return False
        if group_key and group_key in excluded_group_keys:
            return False
        seen.add(key)
        prioritized.append(candidate_url)
        return True

    discovered_candidate_urls = {
        _url_key(url): url
        for url in candidate_urls
        if _url_key(url)
    }

    for preferred_url in [*(extra_preferred_urls or []), *_AZ_LATE_RETRY_DOCUMENT_URLS]:
        candidate_url = discovered_candidate_urls.get(_url_key(preferred_url), preferred_url)
        if _append(candidate_url) and len(prioritized) >= max(1, int(limit)):
            return prioritized

    for candidate_url in candidate_urls:
        parsed = urlparse(str(candidate_url or "").strip())
        if parsed.netloc.lower() != "apps.azsos.gov" or not _AZ_OFFICIAL_DOCUMENT_PATH_RE.search(parsed.path or ""):
            continue
        az_match = re.search(r"/Title_(\d{2})/(\d+)-(\d+)\.(?:pdf|rtf)$", parsed.path or "", re.IGNORECASE)
        if az_match is None:
            continue
        az_title_number = int(az_match.group(1))
        if az_title_number == 1:
            continue
        if _append(candidate_url) and len(prioritized) >= max(1, int(limit)):
            break

    return prioritized


def _prioritize_arizona_seed_document_urls(seed_urls: List[str], *, limit: int) -> List[str]:
    sorted_seed_urls = sorted(
        seed_urls,
        key=lambda value: (
            2 if _is_arizona_official_pdf_url(value) else 1 if _is_rtf_candidate_url(value) else 0,
            _seed_prefetch_priority(value),
        ),
        reverse=True,
    )

    family_buckets: Dict[str, List[str]] = {}
    family_order: List[str] = []
    non_family_urls: List[str] = []
    for seed_url in sorted_seed_urls:
        family_key = _arizona_official_document_title_family_key(seed_url)
        if not family_key:
            non_family_urls.append(seed_url)
            continue
        if family_key not in family_buckets:
            family_buckets[family_key] = []
            family_order.append(family_key)
        family_buckets[family_key].append(seed_url)

    prioritized: List[str] = []
    limit_n = max(1, int(limit))
    while family_order and len(prioritized) < limit_n:
        next_family_order: List[str] = []
        for family_key in family_order:
            bucket = family_buckets.get(family_key) or []
            if not bucket:
                continue
            prioritized.append(bucket.pop(0))
            if len(prioritized) >= limit_n:
                break
            if bucket:
                next_family_order.append(family_key)
        family_order = next_family_order

    if len(prioritized) < limit_n:
        for seed_url in non_family_urls:
            prioritized.append(seed_url)
            if len(prioritized) >= limit_n:
                break

    return prioritized[:limit_n]


def _arizona_late_retry_timeout_s(remaining_state_budget_s: float) -> float:
    remaining_budget = float(remaining_state_budget_s)
    if remaining_budget <= (_AZ_LATE_RETRY_MIN_TIMEOUT_S + 2.0):
        return 0.0
    return max(
        _AZ_LATE_RETRY_MIN_TIMEOUT_S,
        min(_AZ_LATE_RETRY_MAX_TIMEOUT_S, remaining_budget - 2.0),
    )


def _arizona_ranked_fetch_timeout_s(remaining_budget_s: float) -> float:
    remaining_budget = float(remaining_budget_s)
    if remaining_budget <= 0.0:
        return 0.0
    if remaining_budget <= 6.0:
        return max(1.0, min(6.0, remaining_budget - 0.25))
    return max(20.0, min(120.0, remaining_budget - 2.0))


def _has_admin_signal(*, text: str, title: str, url: str) -> bool:
    hay = " ".join([str(text or ""), str(title or ""), str(url or "")])
    if _ADMIN_RULE_TEXT_RE.search(hay):
        return True

    url_value = str(url or "").strip()
    body = str(text or "")
    title_value = str(title or "")
    parsed = urlparse(url_value)
    host = parsed.netloc.lower()
    path = parsed.path or ""

    if _is_vermont_rule_detail_page(text=text, title=title, url=url):
        return True

    if host == "rules.mt.gov" and _MT_POLICY_PATH_RE.fullmatch(path):
        mt_hay = " ".join([title_value, body, url_value])
        if re.search(r"\b\d{1,3}\.\d{1,3}\.\d{2,4}\b", mt_hay):
            return True

    # Utah detail pages often omit explicit "administrative rule" phrasing while still
    # containing the real rule body. Treat canonical detail routes as admin-signal pages
    # when they expose rule-like citations or body markers.
    if host == "adminrules.utah.gov" and _UT_RULE_DETAIL_PATH_RE.search(path):
        ut_hay = " ".join([title_value, body, url_value])
        if re.search(r"\bR\d{1,3}-\d{1,4}\b", ut_hay, re.IGNORECASE):
            return True
        if _RULE_BODY_SIGNAL_RE.search(ut_hay) or _LEGAL_CONTENT_SIGNAL_RE.search(ut_hay):
            return True

    if host == "iar.iga.in.gov" and re.search(r"/code/(?:current|2006)/\d+/\d+(?:\.\d+)?", path, re.IGNORECASE):
        in_hay = " ".join([title_value, body, url_value])
        if re.search(r"\btitle\s+\d+(?:\.\d+)?\b", in_hay, re.IGNORECASE) and re.search(
            r"\b(?:article|rule)\s+\d+(?:\.\d+)?\b",
            in_hay,
            re.IGNORECASE,
        ):
            return True
        if _RULE_BODY_SIGNAL_RE.search(in_hay) and _LEGAL_CONTENT_SIGNAL_RE.search(in_hay):
            return True

    if host == "codeofarrules.arkansas.gov" and path.lower() == "/rules/rule":
        ar_hay = " ".join([title_value, body, url_value])
        if _arkansas_rule_level_from_url(url_value) == "section":
            if re.search(r"\b\d+\s+CAR\s+§\s*[\w.-]+", ar_hay, re.IGNORECASE):
                return True
            if "code of arkansas rules" in ar_hay.lower() and (
                _RULE_BODY_SIGNAL_RE.search(ar_hay) or _LEGAL_CONTENT_SIGNAL_RE.search(ar_hay)
            ):
                return True

    if host in {"www.sos.la.gov", "sos.la.gov"} and "/publisheddocuments/" in path.lower() and path.lower().endswith(".pdf"):
        la_hay = " ".join([title_value, body, url_value])
        la_section_hits = len(re.findall(r"§\s*\d+[A-Za-z0-9.-]*", la_hay, re.IGNORECASE))
        if (
            re.search(r"\btitle\s+\d+\b", la_hay, re.IGNORECASE)
            and re.search(r"\bpart\s+[A-Za-z0-9.-]+\b", la_hay, re.IGNORECASE)
            and re.search(r"\bchapter\s+\d+[A-Za-z0-9.-]*\b", la_hay, re.IGNORECASE)
            and (
                la_section_hits >= 1
                or "authority note:" in la_hay.lower()
                or "historical note:" in la_hay.lower()
            )
        ):
            return True

    if host == "texas-sos.appianportalsgov.com" and path.lower() == "/rules-and-meetings":
        interface = str((parse_qs(parsed.query or "").get("interface") or [""])[0]).strip().upper()
        record_id = str((parse_qs(parsed.query or "").get("recordId") or [""])[0]).strip()
        tx_hay = " ".join([title_value, body])
        if interface == "VIEW_TAC_SUMMARY" and record_id.isdigit():
            if re.search(r"\bRule\s+§\s*\d", tx_hay, re.IGNORECASE):
                return True
            if _RULE_BODY_SIGNAL_RE.search(tx_hay) and _LEGAL_CONTENT_SIGNAL_RE.search(tx_hay):
                return True

    if _looks_like_new_hampshire_archived_rule_inventory(text=body, title=title_value, url=url_value):
        return False

    if _is_new_hampshire_archived_rule_leaf_url(url_value):
        nh_hay = " ".join([title_value, body])
        if _NH_ARCHIVED_RULE_CHAPTER_TEXT_RE.search(nh_hay):
            return True

    if host == "rules.ok.gov" and path.lower() == "/code":
        title_num, section_num = _oklahoma_rule_identifiers_from_url(url_value)
        ok_hay = " ".join([title_value, body, url_value])
        if _OK_RULE_SECTION_NUM_RE.fullmatch(section_num):
            if _LEGAL_CONTENT_SIGNAL_RE.search(ok_hay) or _RULE_BODY_SIGNAL_RE.search(ok_hay):
                return True
        if title_num and not section_num:
            section_hits = len(re.findall(r"\b\d{1,3}:\d+(?:-\d+)+(?:\.\d+)?\b", ok_hay))
            if section_hits >= 2 and _LEGAL_CONTENT_SIGNAL_RE.search(ok_hay):
                return True

    return False


def _looks_like_placeholder_text(text: str) -> bool:
    value = str(text or "").strip()
    if not value:
        return True
    return bool(
        _PORTAL_REFERENCE_RE.search(value)
        or _BAD_DISCOVERY_TEXT_RE.search(value)
        or _looks_like_navigation_page(value)
    )


def _looks_like_raw_html_text(text: str) -> bool:
    value = str(text or "").strip()
    if not value:
        return False
    head = value[:2000]
    return bool(_RAW_HTML_TEXT_RE.search(head))


def _should_abort_vermont_after_lexis_block(
    *,
    state_code: str,
    vermont_lexis_access_blocked: bool,
    statutes_count: int,
) -> bool:
    return state_code == "VT" and vermont_lexis_access_blocked and int(statutes_count) <= 0


def _has_disallowed_discovery_domain(url: str) -> bool:
    host = urlparse(str(url or "").strip()).netloc
    return bool(host and _BAD_DISCOVERY_DOMAIN_RE.search(host))


def _looks_like_navigation_page(text: str) -> bool:
    value = str(text or "").strip()
    if not value:
        return False
    if _LANDING_PAGE_PHRASE_RE.search(value):
        return True
    if _OFF_TOPIC_HISTORY_PAGE_RE.search(value):
        return True
    nav_hits = len(_NAVIGATION_PAGE_TOKEN_RE.findall(value))
    has_rule_body = bool(_RULE_BODY_SIGNAL_RE.search(value))
    if nav_hits >= 3 and not has_rule_body:
        return True
    if _NON_RULE_ADMIN_LANDING_RE.search(value) and not has_rule_body:
        return True
    return False


def _is_vermont_rule_detail_page(*, text: str, title: str, url: str) -> bool:
    url_value = str(url or "").strip()
    parsed = urlparse(url_value)
    host = parsed.netloc.lower()
    path = (parsed.path or "").lower()
    if host != "secure.vermont.gov" or path != "/sos/rules/display.php":
        return False
    rule_id = str((parse_qs(parsed.query or "").get("r") or [""])[0]).strip()
    if not rule_id.isdigit():
        return False
    hay = " ".join([str(title or ""), str(text or "")])
    if not re.search(r"\brule\s+details\b", hay, re.IGNORECASE):
        return False
    if not re.search(r"\brule\s+number\s*:", hay, re.IGNORECASE):
        return False
    return bool(_VT_RULE_DETAIL_TEXT_RE.search(hay))


def _looks_like_non_rule_admin_page(*, text: str, title: str, url: str) -> bool:
    hay = " ".join([str(title or ""), str(url or ""), str(text or "")])
    title_value = str(title or "").strip()
    url_value = str(url or "").strip()
    nav_hits = len(_NAVIGATION_PAGE_TOKEN_RE.findall(hay))
    parsed = urlparse(url_value)
    host = parsed.netloc.lower()
    path = parsed.path or ""
    normalized_path = path.rstrip("/") or "/"
    normalized_path_lower = normalized_path.lower()
    query = parsed.query or ""
    arizona_official_rule_document = _looks_like_arizona_official_rule_document(text=text, title=title, url=url)
    iowa_official_rule_document = _looks_like_iowa_official_rule_document(text=text, title=title, url=url)
    if _is_vermont_rule_detail_page(text=text, title=title, url=url):
        return False
    if iowa_official_rule_document:
        return False
    if _OFF_TOPIC_HISTORY_PAGE_RE.search(hay) and not arizona_official_rule_document:
        return True
    if _SEO_MIRROR_PAGE_RE.search(hay):
        return True
    if host == "azsos.gov" and normalized_path_lower.startswith("/rules") and _AZSOS_RULES_PORTAL_NAV_TEXT_RE.search(hay):
        return True
    if host == "legislature.az.gov" and _AZ_NON_RULE_LEGISLATURE_PATH_RE.fullmatch(normalized_path):
        return True
    if host == "www.azleg.gov" and _AZLEG_NON_ADMIN_SEED_PATH_RE.fullmatch(normalized_path):
        return True
    if host == "apps.azsos.gov" and _AZ_ADMIN_REGISTER_TEXT_RE.search(hay) and not arizona_official_rule_document:
        return True
    if host in {"www.legis.ga.gov", "legis.ga.gov"}:
        return True
    if host in {"legislature.nm.gov", "nmlegis.gov", "www.nmlegis.gov"}:
        return True
    if host == "www.srca.nm.gov" and normalized_path_lower == "/nmac-home/explanation-of-the-new-mexico-administrative-code":
        if all(
            needle in hay.lower()
            for needle in (
                "what are state rules",
                "history of the code",
                "structure of the nmac",
                "anatomy of a rule",
            )
        ):
            return True
    if host == "ltgov.alaska.gov" and normalized_path_lower == "/information/regulations":
        if "proposed regulations" in hay.lower() and "adopted regulations" in hay.lower() and "alaska administrative code" in hay.lower():
            return True
    if host in {"www.sos.arkansas.gov", "sos.arkansas.gov"} and normalized_path_lower == "/rules-regulations":
        if _AR_SOS_PORTAL_TEXT_RE.search(hay) and not _RULE_BODY_SIGNAL_RE.search(hay):
            return True
    if host in {"azsos.gov", "www.azsos.gov"} and normalized_path_lower in {
        "/rules",
        "/rules/arizona-administrative-code",
        "/rules/arizona-administrative-register",
    } and _AZ_RULES_PORTAL_CHROME_RE.search(hay):
        return True
    if host == "oal.ca.gov" and normalized_path in {"/publications", "/publications/ccr"} and _CA_OAL_CCR_LANDING_TEXT_RE.search(hay):
        return True
    if host == "carules.elaws.us" and normalized_path == "/search/allcode":
        return True
    if host in {"www.michigan.gov", "michigan.gov"} and normalized_path_lower.startswith("/lara/bureau-list/moahr/"):
        if "scam alert" in hay.lower() and "licensing and regulatory affairs" in hay.lower():
            return True
    if host in {"www.michigan.gov", "michigan.gov"} and "/lara/-/media/project/websites/lara/moahr/" in normalized_path_lower:
        if re.search(r"(?:administrative-hearing-standard|annual-administrative-code-supplement|_aacs_intro)", normalized_path_lower):
            return True
    if host == "ars.apps.lara.state.mi.us" and normalized_path_lower == "/transaction/rfrtransaction":
        if _MI_RULEMAKING_TRANSACTION_TEXT_RE.search(hay):
            return True
    if host == "web.archive.org" and "gc.nh.gov/rules/about_rules/checkrule.aspx" in url_value.lower():
        if _NH_CHECKRULE_GUIDE_TEXT_RE.search(hay):
            return True
    if host == "www.sos.ks.gov" and normalized_path_lower == "/publications/agency-regulation-resources.html":
        if _KS_RESOURCE_TOOLS_TEXT_RE.search(hay):
            return True
    if host == "govt.westlaw.com" and normalized_path_lower == "/calregs/help":
        return True
    if host == "govt.westlaw.com" and normalized_path_lower == "/calregs/index":
        title_hits = len(re.findall(r"\btitle\s+\d+\b", hay, re.IGNORECASE))
        if title_hits >= 8 and _CA_WESTLAW_TOC_TEXT_RE.search(hay):
            return True
    if host == "govt.westlaw.com" and normalized_path_lower == "/calregs/browse/home/california/californiacodeofregulations":
        title_hits = len(re.findall(r"\btitle\s+\d+\b", hay, re.IGNORECASE))
        division_hits = len(re.findall(r"\bdivision\s+\d+(?:\.\d+)?\b", hay, re.IGNORECASE))
        if (title_hits >= 8 or division_hits >= 2) and _CA_WESTLAW_TOC_TEXT_RE.search(hay):
            return True
    if host == "govt.westlaw.com" and normalized_path_lower.startswith("/calregs/browse/home/california/californiacodeofregulations"):
        toc_hits = len(re.findall(r"\b(?:title|division|chapter|article)\s+\d+(?:\.\d+)?\b", hay, re.IGNORECASE))
        section_link_hits = len(re.findall(r"§\s*\d+", hay, re.IGNORECASE))
        if (toc_hits >= 2 or section_link_hits >= 1) and _CA_WESTLAW_TOC_TEXT_RE.search(hay):
            return True
    if host == "www.ilga.gov" and normalized_path_lower == "/agencies/jcar/admincode":
        if len(re.findall(r"\btitle\s+\d+\b", hay, re.IGNORECASE)) >= 8:
            return True
    if host == "www.ilga.gov" and normalized_path_lower == "/agencies/jcar/parts":
        if len(re.findall(r"\bpart\s+\d+\b", hay, re.IGNORECASE)) >= 6:
            return True
    if host == "www.ilga.gov" and normalized_path_lower == "/agencies/jcar/sections":
        if len(re.findall(r"\bsection\s+\d+\.\d+\b", hay, re.IGNORECASE)) >= 6:
            return True
    if host == "www.ilga.gov" and normalized_path_lower == "/commission/jcar/admincode":
        if len(re.findall(r"\btitle\s+\d+\b", hay, re.IGNORECASE)) >= 8:
            return True
    if host in {"www.tn.gov", "tn.gov"} and normalized_path_lower in {
        "/sos/rules-and-regulations.html",
        "/tga",
    }:
        if "404 - page not found" in hay.lower() or _BAD_DISCOVERY_TEXT_RE.search(hay):
            return True
    if host in {"www.wyoleg.gov", "wyoleg.gov", "legislature.wy.gov"} and normalized_path_lower in {
        "/",
        "/rules",
        "/regulations",
        "/administrative-code",
        "/code-of-regulations",
        "/agency-rules",
        "/policies",
        "/departments",
        "/statestatutes/statutesdownload",
    }:
        if nav_hits >= 3 and not _RULE_BODY_SIGNAL_RE.search(hay):
            return True
    if host == "rules.wyo.gov" and normalized_path_lower in {
        "/",
        "/search.aspx",
        "/help/public/wyoming-administrative-rules-h.html",
    }:
        if _WY_NON_RULE_PORTAL_TEXT_RE.search(hay) and not _RULE_BODY_SIGNAL_RE.search(hay):
            return True
    if host in {"www.mass.gov", "mass.gov"} and _MA_CMR_INVENTORY_PATH_RE.search(normalized_path):
        return True
    if host == "regs.maryland.gov" and _MD_COMAR_INVENTORY_PATH_RE.search(normalized_path):
        return True
    if host == "www.sec.state.ma.us" and normalized_path_lower == "/divisions/pubs-regs/about-cmr.htm":
        return True
    if host in {"malegislature.gov", "www.malegislature.gov", "legislature.ma.gov"} and _MA_GENERAL_LAWS_PATH_RE.search(path):
        return True
    if host == "ars.apps.lara.state.mi.us" and _MI_NON_RULE_PORTAL_PATH_RE.fullmatch(normalized_path):
        return True
    if host == "rules.sos.ri.gov" and _RI_NON_RULE_PORTAL_PATH_RE.fullmatch(normalized_path):
        return True
    if host == "aoa.vermont.gov" and normalized_path_lower == "/icar":
        return True
    if host in {"secure.vermont.gov", "sos.vermont.gov"} and _VT_NON_RULE_PORTAL_PATH_RE.search(path):
        return True
    if host == "secure.vermont.gov" and normalized_path_lower == "/sos/rules/display.php":
        if _VT_PROPOSAL_POSTING_TEXT_RE.search(hay):
            return True
    if host in {"lexisnexis.com", "www.lexisnexis.com", "advance.lexis.com"} and _VT_LEXIS_SHELL_TEXT_RE.search(hay):
        return True
    if host == "legislature.ok.gov" and _OK_NON_SUBSTANTIVE_LEGISLATURE_PATH_RE.fullmatch(path):
        if _OK_LLSDC_TEXT_RE.search(hay) or "home legislators legislation committees calendars" in hay.lower():
            return True
    if host == "rules.ok.gov" and normalized_path_lower == "/code":
        query_params = parse_qs(query)
        title_num = str((query_params.get("titleNum") or [""])[0]).strip()
        section_num = str((query_params.get("sectionNum") or [""])[0]).strip()
        title_hits = len(re.findall(r"\btitle\s+\d+\.", hay, re.IGNORECASE))
        if (
            title_num
            and _OK_RULE_SECTION_NUM_RE.fullmatch(section_num)
            and title_hits >= 8
            and _OK_RULES_PORTAL_SHELL_TEXT_RE.search(hay)
        ):
            return True
    if host == "www.sos.state.tx.us" and _TX_TRANSFER_PATH_RE.search(path):
        if _TX_TRANSFER_NOTICE_TEXT_RE.search(hay):
            return True
    if host == "texas-sos.appianportalsgov.com" and _TX_NON_SUBSTANTIVE_PORTAL_QUERY_RE.search(query):
        return True
    if host == "www.sos.state.tx.us" and _TX_TRANSFER_INDEX_PATH_RE.search(path):
        return True
    if host == "adminrules.utah.gov" and path.startswith("/public/search"):
        return False
    if host in {"rules.utah.gov", "adminrules.utah.gov"} and _UT_NON_RULE_PORTAL_PATH_RE.search(path):
        return True
    if host in {"rules.utah.gov", "adminrules.utah.gov"} and _UT_NON_RULE_TITLE_RE.search(title_value):
        return True
    if host == "rules.utah.gov" and (_UT_NON_RULE_NEWS_PATH_RE.search(path) or _UT_NON_RULE_NEWS_TEXT_RE.search(hay)):
        return True
    if host == "rules.utah.gov" and (_UT_BULLETIN_NEWS_TITLE_RE.search(title_value) or _UT_BULLETIN_PDF_PATH_RE.search(path)):
        return True
    if host == "apps.azsos.gov" and _AZ_RULEMAKING_META_TEXT_RE.search(hay):
        return True
    if _NON_RULE_ADMIN_LANDING_RE.search(hay) and not _RULE_BODY_SIGNAL_RE.search(hay):
        return True
    if _NON_RULE_POLICY_PAGE_RE.search(hay):
        if arizona_official_rule_document and (
            _RULE_BODY_SIGNAL_RE.search(hay) or _LEGAL_CONTENT_SIGNAL_RE.search(hay)
        ):
            return False
        if host == "iar.iga.in.gov" and re.search(
            r"/code/(?:current|2006|2024)/\d+/\d+(?:\.\d+)?(?:/\d+(?:\.\d+)?)?",
            path,
            re.IGNORECASE,
        ):
            if _has_admin_signal(text=text, title=title, url=url) and (
                _RULE_BODY_SIGNAL_RE.search(hay) or _LEGAL_CONTENT_SIGNAL_RE.search(hay)
            ):
                return False
        return True
    if _GENERIC_ADMIN_INDEX_TITLE_RE.fullmatch(title_value) and nav_hits >= 4:
        return True
    return False


def _looks_like_forum_page(*, text: str, title: str, url: str) -> bool:
    host = urlparse(str(url or "").strip()).netloc.lower()
    hay = " ".join([str(title or ""), str(url or ""), str(text or "")])
    if "forum" not in host and "ubbthreads" not in str(url or "").lower():
        return False
    return bool(_FORUM_PAGE_RE.search(hay))


def _looks_like_binary_document_text(*, text: str, url: str) -> bool:
    body = str(text or "")
    if not body:
        return False
    head = body[:800]
    url_value = str(url or "").lower()
    control_count = sum(1 for ch in head if ord(ch) < 32 and ch not in "\n\r\t")
    if "\x00" in head:
        return True
    if _PDF_BINARY_HEADER_RE.search(head):
        return True
    if control_count >= 8 and _PDF_BINARY_TOKEN_RE.search(head):
        return True
    replacement_count = head.count("\ufffd")
    if replacement_count >= 3 and _PDF_BINARY_TOKEN_RE.search(head):
        return True
    if (url_value.endswith(".pdf") or ".pdf?" in url_value) and replacement_count >= 1 and _PDF_BINARY_TOKEN_RE.search(head):
        return True
    return False


def _looks_like_arizona_official_rule_document(*, text: str, title: str, url: str) -> bool:
    body = str(text or "").strip()
    title_value = str(title or "").strip()
    url_value = str(url or "").strip()
    parsed = urlparse(url_value)
    if parsed.netloc.lower() != "apps.azsos.gov" or not _AZ_OFFICIAL_DOCUMENT_PATH_RE.search(parsed.path or ""):
        return False
    hay = " ".join([title_value, body])
    title_hits = len(re.findall(r"\btitle\s+\d+\b", hay, re.IGNORECASE))
    chapter_hits = len(re.findall(r"\bchapter\s+\d+\b", hay, re.IGNORECASE))
    article_hits = len(re.findall(r"\barticle\s+(?:\d+|[ivxlcdm]+)\b", hay, re.IGNORECASE))
    aac_hits = len(re.findall(r"\b\d+\s+a\.a\.c\.\s+\d+\b", hay, re.IGNORECASE))
    return title_hits >= 1 and (chapter_hits >= 1 or article_hits >= 1 or aac_hits >= 1)


def _looks_like_iowa_official_rule_document(*, text: str, title: str, url: str) -> bool:
    body = str(text or "").strip()
    title_value = str(title or "").strip()
    url_value = str(url or "").strip()
    parsed = urlparse(url_value)
    if parsed.netloc.lower() not in {"www.legis.iowa.gov", "legis.iowa.gov"}:
        return False
    if re.fullmatch(r"/docs/iac/agency/\d{2}-\d{2}-\d{4}\.\d+\.pdf", (parsed.path or "").lower()) is None:
        return False

    hay = " ".join([title_value, body])
    chapter_hits = len(re.findall(r"\bchapter\s+\d+[A-Za-z0-9.-]*\b", hay, re.IGNORECASE))
    rule_cite_hits = len(re.findall(r"\b\d+(?:\.\d+)?\(\d+[A-Za-z]?\)", hay))
    authority_hits = len(re.findall(r"\b(?:authority|definitions|rulemaking|department|division|administrative)\b", hay, re.IGNORECASE))
    return len(body) >= 4000 and chapter_hits >= 2 and rule_cite_hits >= 3 and authority_hits >= 4


def _looks_like_arizona_repealed_or_expired_chapter(*, text: str, title: str, url: str) -> bool:
    if not _looks_like_arizona_official_rule_document(text=text, title=title, url=url):
        return False
    hay = " ".join([str(title or "").strip(), str(text or "").strip()[:4000]])
    return bool(re.search(r"\bchapter\s+\d+\.\s+(?:repealed|expired)\b", hay, re.IGNORECASE))


def _looks_like_official_rule_index_page(*, text: str, title: str, url: str) -> bool:
    body = str(text or "").strip()
    title_value = str(title or "").strip()
    url_value = str(url or "").strip()
    if not body or not url_value:
        return False
    parsed = urlparse(url_value)
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    query = parse_qs(parsed.query or "")
    ak_title_hits = len(_AK_AAC_TITLE_ROW_RE.findall(body))
    ga_department_hits = len(_GA_GAC_DEPARTMENT_ROW_RE.findall(body))
    nm_title_hits = len(_NM_NMAC_TITLE_ROW_RE.findall(body))
    mn_chapter_link_hits = len(re.findall(r"/rules/\d{4}/", body, re.IGNORECASE))
    mn_agency_link_hits = len(re.findall(r"/rules/agency/\d+", body, re.IGNORECASE))
    mo_title_link_hits = len(re.findall(r"/adrules/csr/current/\d+csr/\d+csr", body, re.IGNORECASE))
    wyoming_index_like = host == "rules.wyo.gov" and path in {"/search.aspx", "/agencies.aspx"}
    kansas_index_like = host == "www.sos.ks.gov" and path == "/publications/kansas-administrative-regulations.html"
    sd_index_like = host == "sdlegislature.gov" and _SD_RULE_INDEX_PATH_RE.fullmatch(parsed.path or "") is not None
    alaska_index_like = (host == "akrules.elaws.us" and path == "/aac") or (host == "www.akleg.gov" and path == "/basis/aac.asp")
    georgia_index_like = host == "rules.sos.ga.gov" and path == "/gac"
    new_mexico_index_like = host == "www.srca.nm.gov" and _NM_NMAC_TITLES_PATH_RE.fullmatch(parsed.path or "") is not None
    minnesota_index_like = host == "www.revisor.mn.gov" and _MN_RULE_INDEX_PATH_RE.fullmatch(parsed.path or "") is not None
    missouri_index_like = host == "www.sos.mo.gov" and _MO_CSR_INDEX_PATH_RE.fullmatch(parsed.path or "") is not None
    nebraska_index_like = host == "rules.nebraska.gov" and (path == "/" or _NE_RULE_BROWSE_PATH_RE.fullmatch(parsed.path or "") is not None)
    if not wyoming_index_like and not kansas_index_like and not sd_index_like and not alaska_index_like and not georgia_index_like and not new_mexico_index_like and not minnesota_index_like and not missouri_index_like and not nebraska_index_like and not _OFFICIAL_RULE_INDEX_URL_RE.search(url_value):
        return False

    hay = " ".join([title_value, body])
    mt_title_hits = len(_MT_RULE_INDEX_ROW_RE.findall(body))
    sd_row_hits = len(_SD_RULE_INDEX_ROW_RE.findall(body))

    if "administrative rules of montana" in hay.lower() and mt_title_hits >= 5:
        return True
    if host == "www.sos.ks.gov" and path == "/publications/kansas-administrative-regulations.html":
        if "kansas administrative regulations" in hay.lower() and _KS_PORTAL_CHROME_RE.search(hay):
            return True
    if "general provisions" in hay.lower() and mt_title_hits >= 3:
        return True
    if sd_index_like and "administrative rules" in hay.lower() and sd_row_hits >= 8:
        return True
    if alaska_index_like and "alaska administrative code" in hay.lower() and ak_title_hits >= 8:
        return True
    if georgia_index_like and "ga r&r" in hay.lower() and ga_department_hits >= 8:
        return True
    if new_mexico_index_like and "new mexico administrative code" in hay.lower() and nm_title_hits >= 8:
        return True
    if minnesota_index_like and "minnesota administrative rules" in hay.lower() and (mn_chapter_link_hits >= 8 or mn_agency_link_hits >= 4):
        return True
    if missouri_index_like and "code of state regulations" in hay.lower() and mo_title_link_hits >= 8:
        return True
    if nebraska_index_like and "rules and regulations" in hay.lower() and (
        "browse rules by agency" in hay.lower()
        or ("select agency" in hay.lower() and "select title" in hay.lower())
    ):
        return True
    if "alabama administrative code" in hay.lower() and len(re.findall(r"\b(?:agency|chapter|rule|title)\b", hay, re.IGNORECASE)) >= 4:
        return True
    if "arizona administrative code" in hay.lower() and len(re.findall(r"\btitle\s+\d+\b", hay, re.IGNORECASE)) >= 4:
        return True
    if host == "iar.iga.in.gov" and "indiana administrative code" in hay.lower() and len(re.findall(r"\btitle\s+\d+(?:\.\d+)?\b", hay, re.IGNORECASE)) >= 8:
        return True
    if host in {"www.sos.arkansas.gov", "sos.arkansas.gov"} and path.rstrip("/") == "/rules-regulations":
        if _AR_SOS_PORTAL_TEXT_RE.search(hay) and "search arkansas administrative rules" in hay.lower():
            return True
    if host == "www.ilga.gov" and path in {"/agencies/jcar/admincode", "/commission/jcar/admincode", "/commission/jcar/admincode/"}:
        if "administrative code" in hay.lower() and len(re.findall(r"\btitle\s+\d+\b", hay, re.IGNORECASE)) >= 8:
            return True
    if host in {"adminrules.utah.gov", "rules.utah.gov"} and "utah administrative code" in hay.lower() and len(re.findall(r"\b(?:code|rule|agency|administrative)\b", hay, re.IGNORECASE)) >= 4:
        return True
    if host == "adminrules.utah.gov" and path.startswith("/public/search") and "administrative rules search" in hay.lower():
        return True
    if host == "rules.wyo.gov" and path == "/search.aspx":
        mode = str((query.get("mode") or [""])[0]).strip()
        agency_hits = len(re.findall(r"\bagency\b", hay, re.IGNORECASE))
        result_hits = len(re.findall(r"\bresult(?:\(s\)|s)?\b", hay, re.IGNORECASE))
        if mode == "7" and "administrative rules (code)" in hay.lower() and agency_hits >= 2 and result_hits >= 2:
            return True
    if host == "sharetngov.tnsosfiles.com" and path in {
        "/sos/rules/index.htm",
        "/sos/pub/tar/index.htm",
        "/sos/rules/rules2.htm",
        "/sos/rules/rules_list.shtml",
        "/sos/rules/effectives/effectives.htm",
        "/sos/rules/tenncare.htm",
    }:
        if "tennessee department of state: publications" in hay.lower() and (
            "administrative register" in hay.lower()
            or "rules & regulations" in hay.lower()
            or "effective rules" in hay.lower()
            or "view all effective rule chapters" in hay.lower()
            or "view effective rules by month" in hay.lower()
            or "archived rule filings" in hay.lower()
            or "tenncare rules" in hay.lower()
        ):
            return True
    return False


def _looks_like_rule_inventory_page(*, text: str, title: str, url: str) -> bool:
    body = str(text or "").strip()
    title_value = str(title or "").strip()
    url_value = str(url or "").strip()
    if not body or not url_value:
        return False
    if _looks_like_official_rule_index_page(text=body, title=title_value, url=url_value):
        return True

    host = urlparse(url_value).netloc.lower()
    path = (urlparse(url_value).path or "").lower()
    query = parse_qs(urlparse(url_value).query or "")
    hay = " ".join([title_value, body])
    arizona_official_rule_document = _looks_like_arizona_official_rule_document(text=body, title=title_value, url=url_value)
    chapter_hits = len(re.findall(r"\bchapter\b", body, re.IGNORECASE))
    subchapter_hits = len(re.findall(r"\bsubchapter\b", body, re.IGNORECASE))
    sd_row_hits = len(_SD_RULE_INDEX_ROW_RE.findall(body))
    ak_chapter_hits = len(_AK_AAC_CHAPTER_ROW_RE.findall(body))
    ak_section_hits = len(_AK_AAC_SECTION_ROW_RE.findall(body))
    ga_subject_hits = len(_GA_GAC_SUBJECT_ROW_RE.findall(body))
    ga_rule_hits = len(_GA_GAC_RULE_ROW_RE.findall(body))
    nm_title_hits = len(_NM_NMAC_TITLE_ROW_RE.findall(body))
    nm_chapter_hits = len(_NM_NMAC_CHAPTER_ROW_RE.findall(body))
    nm_rule_hits = len(_NM_NMAC_RULE_ROW_RE.findall(body))
    mt_rule_hits = len(re.findall(r"\b\d{1,3}\.\d{1,3}\.\d{2,4}\b", body))
    nh_prefix_hits = len(_NH_ARCHIVED_RULE_PREFIX_RE.findall(hay))
    ca_title_hits = len(re.findall(r"\btitle\s+\d+\b", hay, re.IGNORECASE))
    ca_division_hits = len(re.findall(r"\bdivision\s+\d+(?:\.\d+)?\b", hay, re.IGNORECASE))
    ca_chapter_hits = len(re.findall(r"\bchapter\s+\d+(?:\.\d+)?\b", hay, re.IGNORECASE))
    ca_article_hits = len(re.findall(r"\barticle\s+\d+(?:\.\d+)?\b", hay, re.IGNORECASE))
    ca_section_hits = len(re.findall(r"§\s*\d+", hay, re.IGNORECASE))
    il_title_hits = len(re.findall(r"\btitle\s+\d+\b", hay, re.IGNORECASE))
    il_part_hits = len(re.findall(r"\bpart\s+\d+\b", hay, re.IGNORECASE))
    il_section_hits = len(re.findall(r"\bsection\s+\d+\.\d+\b", hay, re.IGNORECASE))
    wy_rule_hits = len(re.findall(r'data-whatever=["\']([1-9]\d*)["\']', body, re.IGNORECASE))
    wy_program_hits = len(re.findall(r'class=["\'][^"\']*\bprogram_id\b[^"\']*["\']', body, re.IGNORECASE))
    wy_result_hits = len(re.findall(r"\bresult(?:\(s\)|s)?\b", hay, re.IGNORECASE))
    wy_reference_hits = len(re.findall(r"\breference\s+number\b", hay, re.IGNORECASE))
    ct_title_hits = len(_CT_EREGS_TITLE_ROW_RE.findall(hay))
    ct_subtitle_hits = len(_CT_EREGS_SUBTITLE_ROW_RE.findall(hay))
    ct_section_hits = len(_CT_EREGS_SECTION_ROW_RE.findall(hay))
    co_rule_hits = len(_CO_CCR_RULE_ROW_RE.findall(hay))
    mn_chapter_link_hits = len(re.findall(r"/rules/\d{4}/", body, re.IGNORECASE))
    mn_agency_link_hits = len(re.findall(r"/rules/agency/\d+", body, re.IGNORECASE))
    mn_part_hits = len(re.findall(r"\bpart(?:s)?\b", hay, re.IGNORECASE))
    mo_title_link_hits = len(re.findall(r"/adrules/csr/current/\d+csr/\d+csr", body, re.IGNORECASE))
    mo_pdf_link_hits = len(re.findall(r'/cmsimages/adrules/csr/current/\d+csr/[^"\'\s>]+\.pdf', body, re.IGNORECASE))
    mo_division_hits = len(re.findall(r"\bdivision\s+\d+\b", hay, re.IGNORECASE))
    ne_download_hits = len(re.findall(r"\bdownload\s+chapter\b", hay, re.IGNORECASE))

    if host == "rules.mt.gov" and "/policies/" in path:
        return False

    if host in {"www.sos.state.co.us", "www.coloradosos.gov"} and (_CO_CCR_GENERATE_RULE_PDF_PATH_RE.fullmatch(path) or _CO_CCR_PDF_PATH_RE.fullmatch(path)):
        return False
    if host in {"www.sos.state.co.us", "www.coloradosos.gov"} and _CO_CCR_WELCOME_PATH_RE.fullmatch(path):
        if "code of colorado regulations" in hay.lower() and "official publication of the state administrative rules" in hay.lower():
            return True
    if host in {"www.sos.state.co.us", "www.coloradosos.gov"} and _CO_CCR_DEPT_LIST_PATH_RE.fullmatch(path):
        if "browse rules" in hay.lower() and "ccr#" in hay.lower() and hay.lower().count("department of") >= 4:
            return True
    if host in {"www.sos.state.co.us", "www.coloradosos.gov"} and _CO_CCR_AGENCY_LIST_PATH_RE.fullmatch(path):
        if "deptid=" in (urlparse(url_value).query or "").lower():
            return True
        if "browse rules" in hay.lower() and "ccr#" in hay.lower() and hay.lower().count("division") >= 3:
            return True
    if host in {"www.sos.state.co.us", "www.coloradosos.gov"} and _CO_CCR_DOC_LIST_PATH_RE.fullmatch(path):
        if (
            "code of colorado regulations" in hay.lower()
            or "colorado code of regulations" in hay.lower()
            or ("browse rules" in hay.lower() and "all versions" not in hay.lower() and co_rule_hits >= 4)
        ):
            return True
    if host in {"www.sos.state.co.us", "www.coloradosos.gov"} and _CO_CCR_DISPLAY_RULE_PATH_RE.fullmatch(path):
        if "current version" in hay.lower() and "all versions" in hay.lower() and "rulemaking details" in hay.lower():
            return True

    if host == "eregulations.ct.gov" and _CT_EREGS_SECTION_PATH_RE.fullmatch(path):
        return False
    if host == "eregulations.ct.gov" and _CT_EREGS_ROOT_PATH_RE.fullmatch(path):
        if "browse the regulations of connecticut state agencies" in hay.lower() and "select a title to browse its contents" in hay.lower() and ct_title_hits >= 4:
            return True
    if host == "eregulations.ct.gov" and _CT_EREGS_TITLE_PATH_RE.fullmatch(path):
        if "select a subtitle to browse its contents" in hay.lower() and ct_subtitle_hits >= 2:
            return True
    if host == "eregulations.ct.gov" and _CT_EREGS_SUBTITLE_PATH_RE.fullmatch(path):
        if "select a section to browse its contents" in hay.lower() and ct_section_hits >= 4:
            return True

    if host == "www.revisor.mn.gov" and _MN_RULE_INDEX_PATH_RE.fullmatch(path):
        if "minnesota administrative rules" in hay.lower() and (mn_chapter_link_hits >= 8 or mn_agency_link_hits >= 4):
            return True
    if host == "www.revisor.mn.gov" and _MN_RULE_AGENCY_PATH_RE.fullmatch(path):
        if "minnesota administrative rules" in hay.lower() and mn_chapter_link_hits >= 4 and mn_part_hits >= 2:
            return True
    if host == "www.sos.mo.gov" and _MO_CSR_INDEX_PATH_RE.fullmatch(path):
        if "code of state regulations" in hay.lower() and mo_title_link_hits >= 8:
            return True
    if host == "www.sos.mo.gov" and _MO_CSR_TITLE_PATH_RE.fullmatch(path):
        if "code of state regulations" in hay.lower() and mo_pdf_link_hits >= 6 and mo_division_hits >= 2:
            return True
    if host == "rules.nebraska.gov" and path in {"/", "/browse-rules"}:
        if "rules and regulations" in hay.lower() and (
            "browse rules by agency" in hay.lower()
            or ("select agency" in hay.lower() and "select title" in hay.lower())
        ):
            return True
    if host == "rules.nebraska.gov" and path == "/rules":
        if ("rules and regulations" in hay.lower() and "select title" in hay.lower()) or ne_download_hits >= 2:
            return True

    if host == "rules.sos.ga.gov" and _GA_GAC_RULE_PATH_RE.fullmatch(path):
        return False
    if host == "rules.sos.ga.gov" and path == "/gac":
        if ga_subject_hits >= 4 or len(_GA_GAC_DEPARTMENT_ROW_RE.findall(hay)) >= 8:
            return True
    if host == "rules.sos.ga.gov" and _GA_GAC_DEPARTMENT_PATH_RE.fullmatch(path):
        if chapter_hits >= 2 and ga_subject_hits >= 3:
            return True
    if host == "rules.sos.ga.gov" and _GA_GAC_CHAPTER_PATH_RE.fullmatch(path):
        if ga_subject_hits >= 4:
            return True
    if host == "rules.sos.ga.gov" and _GA_GAC_SUBJECT_PATH_RE.fullmatch(path):
        if ga_rule_hits >= 2:
            return True

    if host == "www.srca.nm.gov" and path == "/nmac-home":
        if "nmac titles" in hay.lower() and _NM_NMAC_PORTAL_TEXT_RE.search(hay):
            return True
    if host == "www.srca.nm.gov" and path == "/nmac-home/explanation-of-the-new-mexico-administrative-code":
        if _NM_NMAC_PORTAL_TEXT_RE.search(hay) and "what are state rules" in hay.lower():
            return True
    if host == "www.srca.nm.gov" and _NM_NMAC_TITLES_PATH_RE.fullmatch(path):
        if nm_title_hits >= 8 and _NM_NMAC_PORTAL_TEXT_RE.search(hay):
            return True
    if host == "www.srca.nm.gov" and _NM_NMAC_TITLE_PATH_RE.fullmatch(path):
        if nm_chapter_hits >= 6 and nm_rule_hits >= 4 and _NM_NMAC_PORTAL_TEXT_RE.search(hay):
            return True
    if host == "www.srca.nm.gov" and _NM_NMAC_CHAPTER_PATH_RE.fullmatch(path):
        if nm_chapter_hits >= 6 and nm_rule_hits >= 4 and _NM_NMAC_PORTAL_TEXT_RE.search(hay):
            return True

    if host == "akrules.elaws.us" and _AK_AAC_SECTION_PATH_RE.fullmatch(path):
        return False
    if host == "akrules.elaws.us" and _AK_BOOKVIEW_PATH_RE.fullmatch(path):
        return True
    if host == "akrules.elaws.us" and _AK_AAC_TITLE_PATH_RE.fullmatch(path):
        if ak_chapter_hits >= 1 and "alaska administrative code" in hay.lower():
            return True
    if host == "akrules.elaws.us" and _AK_AAC_CHAPTER_PATH_RE.fullmatch(path):
        if ak_section_hits >= 2 and "alaska administrative code" in hay.lower():
            return True
    if host == "ltgov.alaska.gov" and path.rstrip("/") == "/information/regulations":
        if "proposed regulations" in hay.lower() and "adopted regulations" in hay.lower() and "alaska administrative code" in hay.lower():
            return True
    if host == "www.akleg.gov" and path == "/basis/aac.asp":
        if len(_AK_AAC_TITLE_ROW_RE.findall(hay)) >= 8 and "this page is no longer used" in hay.lower():
            return True

    if host == "rules.mt.gov" and "/sections/" in path and (chapter_hits >= 3 or subchapter_hits >= 2 or mt_rule_hits >= 2):
        return True
    if host == "www.sos.ks.gov" and path == "/publications/pubs_kar_regs.aspx":
        ks_rule_hits = len(_KS_RULE_LISTING_ROW_RE.findall(body))
        if "kansas administrative regulations" in hay.lower() and "agency" in hay.lower() and ks_rule_hits >= 8:
            return True
    if host in {"sosmt.gov", "www.sosmt.gov"} and "/arm" in url_value.lower() and (
        mt_rule_hits >= 2 or "administrative rules of montana" in hay.lower() or
        len(re.findall(r"\bTitle\s+\d+\b", body, re.IGNORECASE)) >= 3
    ):
        return True
    if host == "admincode.legislature.state.al.us" and path == "/administrative-code":
        if not _AL_RULE_NUMBER_RE.fullmatch(_alabama_public_code_number_from_url(url_value)):
            return True
    if host == "admincode.legislature.state.al.us" and chapter_hits >= 3:
        return True
    if host in {"www.sos.arkansas.gov", "sos.arkansas.gov"} and path.rstrip("/") == "/rules-regulations":
        if _AR_SOS_PORTAL_TEXT_RE.search(hay) and "search arkansas administrative rules" in hay.lower():
            return True
    if host == "codeofarrules.arkansas.gov" and path == "/rules/search":
        if "code of arkansas rules" in hay.lower() and "search" in title_value.lower():
            return True
    if host == "codeofarrules.arkansas.gov" and path == "/rules/rule":
        arkansas_level = _arkansas_rule_level_from_url(url_value)
        if arkansas_level in {"title", "chapter", "subchapter", "part", "subpart"}:
            if "code of arkansas rules" in hay.lower() or chapter_hits >= 2 or subchapter_hits >= 1:
                return True
    if host == "sos-rules-reg.ark.org" and (path.startswith("/rules/search") or path.startswith("/rules/text_search")):
        if "arkansas secretary of state" in hay.lower() and (
            "search arkansas agencies" in hay.lower()
            or "search results" in hay.lower()
            or "full text search results" in hay.lower()
            or len(re.findall(r"/rules/pdf/", body, re.IGNORECASE)) >= 3
        ):
            return True
    if host == "rules.wyo.gov" and path == "/search.aspx":
        mode = str((query.get("mode") or [""])[0]).strip()
        agency_hits = len(re.findall(r"\bagency\b", hay, re.IGNORECASE))
        if mode == "7" and "administrative rules (code)" in hay.lower() and agency_hits >= 2 and wy_result_hits >= 2:
            return True
    if host == "rules.wyo.gov" and path == "/ajaxhandler.ashx":
        handler = str((query.get("handler") or [""])[0]).strip().lower()
        if handler == "search_getprogramrules" and chapter_hits >= 2 and wy_reference_hits >= 2:
            return True
    sd_detail_match = _SD_RULE_DETAIL_PATH_RE.fullmatch(urlparse(url_value).path or "")
    if host == "sdlegislature.gov" and _SD_RULE_INDEX_PATH_RE.fullmatch(urlparse(url_value).path or "") and sd_row_hits >= 8:
        return True
    if host == "sdlegislature.gov" and sd_detail_match:
        rule_value = str(sd_detail_match.group("rule") or "").strip()
        if rule_value.count(":") == 1:
            return True
    if host == "apps.azsos.gov" and _AZ_ADMIN_REGISTER_TEXT_RE.search(hay) and not arizona_official_rule_document:
        return True
    if host == "mirules.elaws.us" and path == "/search/allcode":
        if _MI_ELAWS_INDEX_TEXT_RE.search(hay):
            return True
    if host == "sos.tn.gov" and path in {
        "/publications/services/administrative-register",
        "/publications/services/effective-rules-and-regulations-of-the-state-of-tennessee",
    }:
        if _TN_SOS_SERVICE_PAGE_TEXT_RE.search(hay):
            return True
    if _looks_like_new_hampshire_archived_rule_inventory(text=body, title=title_value, url=url_value):
        return True
    if _is_new_hampshire_archived_rule_leaf_url(url_value):
        return False
    if host == "web.archive.org" and "gc.nh.gov/rules" in url_value.lower() and (
        "rules listed by state agency" in hay.lower() or nh_prefix_hits >= 12
    ):
        return True
    if host == "web.archive.org" and url_value.rstrip("/").endswith("https://gc.nh.gov/rules"):
        if _NH_RULES_PORTAL_TEXT_RE.search(hay):
            return True
    if host in {"lexisnexis.com", "www.lexisnexis.com", "advance.lexis.com"}:
        if _VT_LEXIS_DOC_PATH_RE.fullmatch(urlparse(url_value).path or ""):
            return False
        if _VT_LEXIS_TOC_TEXT_RE.search(hay):
            return True
    if host == "www.ilga.gov" and path in {"/agencies/jcar/admincode", "/commission/jcar/admincode", "/commission/jcar/admincode/"}:
        if "administrative code" in hay.lower() and il_title_hits >= 8:
            return True
    if host == "www.ilga.gov" and path == "/agencies/jcar/parts":
        if il_part_hits >= 6 and "administrative code" in hay.lower():
            return True
    if host == "www.ilga.gov" and path == "/agencies/jcar/sections":
        if il_section_hits >= 6 and "view entire part" in hay.lower():
            return True
    if host == "sharetngov.tnsosfiles.com" and path in {
        "/sos/rules/index.htm",
        "/sos/pub/tar/index.htm",
        "/sos/rules/rules2.htm",
        "/sos/rules/rules_list.shtml",
        "/sos/rules/effectives/effectives.htm",
        "/sos/rules/tenncare.htm",
    }:
        if (
            "administrative register" in hay.lower()
            or "effective rules" in hay.lower()
            or "view all effective rule chapters" in hay.lower()
            or "view effective rules by month" in hay.lower()
            or "archived rule filings" in hay.lower()
            or "tenncare rules" in hay.lower()
        ):
            return True
    if host == "sharetngov.tnsosfiles.com" and re.search(
        r"^/sos/rules/\d{4}/(?:\d{4}|[\d-]+/[\d-]+)\.htm$",
        path,
        re.IGNORECASE,
    ):
        if (
            "click on the rule you want to view or print" in hay.lower()
            and "keywords may be searched for in individual pdf files" in hay.lower()
        ):
            return True
    if host in {"www.mass.gov", "mass.gov"} and _MA_CMR_INVENTORY_PATH_RE.search(path):
        return True
    if host == "www.sec.state.ma.us" and path == "/divisions/pubs-regs/about-cmr.htm":
        if "code of massachusetts regulations" in hay.lower() or "cmr" in hay.lower():
            return True
    if host == "govt.westlaw.com" and path == "/calregs/index":
        if ca_title_hits >= 8 and _CA_WESTLAW_TOC_TEXT_RE.search(hay):
            return True
    if host == "govt.westlaw.com" and path.startswith("/calregs/browse/home/california/californiacodeofregulations"):
        if (
            ca_division_hits >= 1
            or ca_chapter_hits >= 1
            or ca_article_hits >= 1
            or ca_section_hits >= 1
            or ca_title_hits >= 8
        ) and _CA_WESTLAW_TOC_TEXT_RE.search(hay):
            return True
    return False


def _looks_like_shallow_montana_inventory_page(*, text: str, title: str, url: str) -> bool:
    body = str(text or "").strip()
    title_value = str(title or "").strip()
    url_value = str(url or "").strip()
    parsed = urlparse(url_value)
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    if host != "rules.mt.gov" or "/browse/collections/" not in path:
        return False

    hay = " ".join([title_value, body])
    chapter_hits = len(re.findall(r"\bchapter\b", body, re.IGNORECASE))
    subchapter_hits = len(re.findall(r"\bsubchapter\b", body, re.IGNORECASE))
    title_hits = len(re.findall(r"\btitle\b", body, re.IGNORECASE))
    arm_rule_hits = len(re.findall(r"\b(?:arm\s*)?\d{1,2}\.\d{1,2}\.\d{2,4}\b", hay, re.IGNORECASE))
    authority_hits = len(re.findall(r"\b(?:authority|implementing|history|effective|amd\.|rep\.|trans)\b", hay, re.IGNORECASE))
    nav_hits = len(_NAVIGATION_PAGE_TOKEN_RE.findall(hay))
    policy_detail_hits = len(
        re.findall(
            r"\b(?:rule version|active version|contact information|rule history|relevant mar notices|references|referenced by|collapse all|view more|back)\b",
            hay,
            re.IGNORECASE,
        )
    )
    show_not_effective = "show not effective" in hay.lower()

    if re.fullmatch(r"/browse/collections/[0-9a-fA-F-]+", path):
        return True

    if "/sections/" in path:
        if authority_hits >= 2 or policy_detail_hits >= 2:
            return False
        return True

    if authority_hits >= 2 or (arm_rule_hits > 0 and policy_detail_hits > 0):
        return False
    if "/sections/" in path and show_not_effective and (chapter_hits >= 1 or subchapter_hits >= 1):
        return True
    if chapter_hits >= 3:
        return True
    if subchapter_hits >= 2:
        return True
    if title_hits >= 10 and nav_hits >= 4 and "administrative rules of montana" in hay.lower():
        return True
    return False


def _candidate_montana_rule_urls_from_text(*, text: str, url: str, limit: int = 12) -> List[str]:
    """Extract candidate Montana ARM rule URLs from scrape text.

    Handles:
        - ``rules.mt.gov/browse/collections/<id>/sections/`` pages: extracts linked
            ``/policies/<uuid>`` detail URLs from rendered HTML
    - ``sosmt.gov/arm/`` index pages: extracts Title-level deep links to rules.mt.gov sections
    """
    body = str(text or "")
    url_value = str(url or "").strip()
    parsed = urlparse(url_value)
    host = parsed.netloc.lower()
    limit_n = max(1, int(limit))
    out: List[str] = []
    seen: set = set()

    if host == "rules.mt.gov":
        return _candidate_montana_policy_urls_from_html(html=body, url=url_value, limit=limit_n)

    if host in {"sosmt.gov", "www.sosmt.gov"}:
        # ARM index pages on sosmt.gov link out to rules.mt.gov collection/section URLs.
        # Extract absolute and relative links that look like ARM Title entries.
        for href in re.findall(r'href=["\']([^"\']+)["\']', body):
            href = href.strip()
            if not href:
                continue
            if href.startswith(("http://", "https://")) and "rules.mt.gov" in href:
                candidate = href
            elif href.startswith("/") and "rules.mt.gov" not in href:
                continue
            elif re.search(r"rules\.mt\.gov", href):
                candidate = href if href.startswith("http") else "https://" + href.lstrip("/")
            else:
                continue
            if candidate in seen:
                continue
            seen.add(candidate)
            out.append(candidate)
            if len(out) >= limit_n:
                break
        return out

    return []


def _candidate_utah_rule_urls_from_public_api(*, url: str, limit: int = 24) -> List[str]:
    url_value = str(url or "").strip()
    parsed = urlparse(url_value)
    if parsed.netloc.lower() != "adminrules.utah.gov":
        return []
    if not (
        parsed.path.startswith("/public/search")
        or parsed.path.startswith("/api/public/searchRuleDataTotal/")
    ):
        return []

    search_term = ""
    path_parts = [unquote(part).strip() for part in parsed.path.split("/") if part]
    if len(path_parts) >= 3 and path_parts[0] == "public" and path_parts[1] == "search":
        candidate_term = str(path_parts[2] or "").strip()
        if candidate_term.lower() not in {
            "current rules",
            "proposed",
            "emergency",
            "expired emergency",
            "repealed",
            "superseded",
        }:
            search_term = candidate_term
    elif len(path_parts) >= 5 and path_parts[:3] == ["api", "public", "searchRuleDataTotal"]:
        candidate_term = str(path_parts[3] or "").strip()
        if candidate_term.lower() not in {
            "current rules",
            "proposed",
            "emergency",
            "expired emergency",
            "repealed",
            "superseded",
        }:
            search_term = candidate_term
    search_terms: List[str] = []
    if not search_term or search_term.lower() == "undefined":
        # Utah's empty search route no longer serves JSON for the legacy
        # `undefined` token. The broad `R` query still returns the current-rule
        # index, but it is slow enough to consume most bounded state budgets.
        # Prefer narrower stable prefixes first; they still return more than
        # enough rule-detail URLs for the initial bootstrap backlog.
        search_terms = ["R51", "R52", "R58", "R59", "R70", "R590"]
    else:
        search_terms = [search_term]

    effective_limit = max(1, int(limit))
    if (not search_term or search_term.lower() == "undefined") or (len(search_terms) == 1 and len(search_terms[0]) <= 1):
        # Broad single-letter Utah bootstrap queries can be large and slow.
        # Keep the initial detail backlog intentionally small so bounded daemon
        # runs can move on to rule fetches instead of spending the whole state
        # budget enumerating the public search index.
        effective_limit = min(effective_limit, 8)
    out: List[str] = []
    seen = set()

    for active_search_term in search_terms:
        encoded_search_term = quote(active_search_term, safe="")
        api_url = f"https://adminrules.utah.gov/api/public/searchRuleDataTotal/{encoded_search_term}/Current%20Rules"

        try:
            response = requests.get(
                api_url,
                timeout=25,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Accept": "application/json, text/plain, */*",
                    "Referer": url_value or "https://adminrules.utah.gov/public/search//Current%20Rules",
                },
            )
            response.raise_for_status()
            payload = response.json()
        except Exception:
            continue

        for agency in payload or []:
            if not isinstance(agency, dict):
                continue
            for program in agency.get("programs") or []:
                if not isinstance(program, dict):
                    continue
                for rule in program.get("rules") or []:
                    if not isinstance(rule, dict):
                        continue
                    link_to_rule = str(rule.get("linkToRule") or "").strip()
                    if link_to_rule:
                        candidate_url = urljoin(
                            "https://adminrules.utah.gov/public/rule/",
                            link_to_rule.replace(" ", "%20"),
                        )
                        _cache_utah_rule_detail_metadata(candidate_url, rule)
                        key = _url_key(candidate_url)
                        if key and key not in seen:
                            seen.add(key)
                            out.append(candidate_url)
                            if len(out) >= effective_limit:
                                return out
    return out


def _candidate_arkansas_rule_urls_from_html(*, html: str, page_url: str = "", limit: int = 12) -> List[str]:
    body = str(html or "")
    if not body:
        return []

    parsed_page = urlparse(str(page_url or "").strip())
    host = parsed_page.netloc.lower()
    if host not in {"sos-rules-reg.ark.org", "codeofarrules.arkansas.gov", "ark.org"}:
        return []

    limit_n = max(1, int(limit))
    out: List[str] = []
    seen: set[str] = set()
    base_url = page_url or (
        "https://sos-rules-reg.ark.org/rules/search/new"
        if host in {"sos-rules-reg.ark.org", "ark.org"}
        else "https://codeofarrules.arkansas.gov/Rules/Search"
    )

    for href in re.findall(r'href=["\']([^"\']+)["\']', body, re.IGNORECASE):
        raw_href = unescape(str(href or "").strip())
        if not raw_href:
            continue
        normalized_href = raw_href.replace("&sect;ionID", "&sectionID")
        normalized_href = normalized_href.replace("§ionID", "&sectionID")
        candidate_url = urldefrag(urljoin(base_url, normalized_href)).url
        candidate_url = candidate_url.replace("&sect;ionID", "&sectionID")
        candidate_url = candidate_url.replace("§ionID", "&sectionID")
        parsed_candidate = urlparse(candidate_url)
        candidate_host = parsed_candidate.netloc.lower()
        candidate_path = parsed_candidate.path or ""
        candidate_query = parsed_candidate.query or ""

        keep = False
        if candidate_host == "sos-rules-reg.ark.org":
            keep = bool(
                re.search(r"^/rules/pdf/[\w.-]+\.pdf$", candidate_path, re.IGNORECASE)
                or re.search(r"^/rules/(?:search/\d+|text_search/\w+/\d+)$", candidate_path, re.IGNORECASE)
            )
        elif candidate_host == "codeofarrules.arkansas.gov":
            keep = candidate_path.lower() == "/rules/rule" and "leveltype=" in candidate_query.lower()

        if not keep:
            continue
        key = _url_key(candidate_url)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(candidate_url)
        if len(out) >= limit_n:
            break

    return out


def _arkansas_rule_level_from_url(url: str) -> str:
    parsed = urlparse(str(url or "").strip())
    if parsed.netloc.lower() != "codeofarrules.arkansas.gov":
        return ""
    if (parsed.path or "").lower() != "/rules/rule":
        return ""
    return str((parse_qs(parsed.query or "").get("levelType") or [""])[0]).strip().lower()


def _arkansas_rule_url_from_tree_node(node: Dict[str, Any]) -> str:
    if not isinstance(node, dict):
        return ""
    if str(node.get("nodeType") or "").strip().upper() != "SECTION":
        return ""
    section_id = str(node.get("sectionID") or "").strip()
    if not section_id:
        return ""
    params = {
        "levelType": "section",
        "titleID": str(node.get("titleID") or "").strip(),
        "chapterID": str(node.get("chapterID") or "").strip(),
        "subChapterID": str(node.get("subchapterID") or "").strip(),
        "partID": str(node.get("partID") or "").strip(),
        "subPartID": str(node.get("subpartID") or "").strip(),
        "sectionID": section_id,
    }
    if not params["titleID"] or not params["chapterID"]:
        return ""
    return "https://codeofarrules.arkansas.gov/Rules/Rule?" + urlencode(params)


def _fetch_arkansas_tree_nodes(
    session: requests.Session,
    *,
    level_type: str,
    title_id: str = "",
    chapter_id: str = "",
    subchapter_id: str = "",
    timeout: float = 25.0,
    headers: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    params = {"levelType": str(level_type or "").strip().upper()}
    if title_id:
        params["titleID"] = str(title_id).strip()
    if chapter_id:
        params["chapterID"] = str(chapter_id).strip()
    if subchapter_id:
        params["subchapterID"] = str(subchapter_id).strip()

    try:
        response = session.get(
            "https://codeofarrules.arkansas.gov/Home/GetRulesTreeViewData",
            params=params,
            timeout=timeout,
            headers=headers,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception:
        return []

    out: List[Dict[str, Any]] = []
    for node in payload or []:
        if isinstance(node, dict):
            out.append(node)
    return out


async def _discover_arkansas_rule_document_urls(*, seed_urls: List[str], limit: int = 8) -> List[str]:
    relevant_seed_urls = [
        url
        for url in seed_urls
        if urlparse(str(url or "").strip()).netloc.lower()
        in {"sos-rules-reg.ark.org", "ark.org", "www.sos.arkansas.gov", "codeofarrules.arkansas.gov"}
    ]
    if not relevant_seed_urls:
        return []

    limit_n = max(1, int(limit))

    def _run() -> List[str]:
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        discovered_urls: List[str] = []
        seen: set[str] = set()
        seen_title_ids: set[str] = set()
        session = requests.Session()

        def _record(urls: List[str], *, pdf_only: bool = False) -> bool:
            for candidate_url in urls:
                if pdf_only and not _is_pdf_candidate_url(candidate_url):
                    continue
                key = _url_key(candidate_url)
                if not key or key in seen:
                    continue
                seen.add(key)
                discovered_urls.append(candidate_url)
                if len(discovered_urls) >= limit_n:
                    return True
            return False

        def _record_arkansas_title_urls(urls: List[str]) -> None:
            for candidate_url in urls:
                parsed = urlparse(candidate_url)
                if parsed.netloc.lower() != "codeofarrules.arkansas.gov":
                    continue
                if (parsed.path or "").lower() != "/rules/rule":
                    continue
                title_id = str((parse_qs(parsed.query or "").get("titleID") or [""])[0]).strip()
                if title_id:
                    seen_title_ids.add(title_id)

        def _expand_title_ids(title_ids: List[str]) -> bool:
            for title_id in title_ids:
                if not title_id:
                    continue
                chapter_nodes = _fetch_arkansas_tree_nodes(
                    session,
                    level_type="CHAPTER",
                    title_id=title_id,
                    headers=headers,
                )
                for chapter_node in chapter_nodes:
                    chapter_id = str(chapter_node.get("nodeID") or chapter_node.get("chapterID") or "").strip()
                    if not chapter_id:
                        continue

                    subchapter_nodes = _fetch_arkansas_tree_nodes(
                        session,
                        level_type="SUBCHAPTER",
                        title_id=title_id,
                        chapter_id=chapter_id,
                        headers=headers,
                    )
                    if subchapter_nodes:
                        for subchapter_node in subchapter_nodes:
                            subchapter_id = str(
                                subchapter_node.get("nodeID") or subchapter_node.get("subchapterID") or ""
                            ).strip()
                            if not subchapter_id:
                                continue
                            section_nodes = _fetch_arkansas_tree_nodes(
                                session,
                                level_type="SECTION",
                                title_id=title_id,
                                chapter_id=chapter_id,
                                subchapter_id=subchapter_id,
                                headers=headers,
                            )
                            section_urls = [
                                section_url
                                for section_url in (
                                    _arkansas_rule_url_from_tree_node(node)
                                    for node in section_nodes
                                )
                                if section_url
                            ]
                            if _record(section_urls):
                                return True
                    else:
                        section_nodes = _fetch_arkansas_tree_nodes(
                            session,
                            level_type="SECTION",
                            title_id=title_id,
                            chapter_id=chapter_id,
                            headers=headers,
                        )
                        section_urls = [
                            section_url
                            for section_url in (
                                _arkansas_rule_url_from_tree_node(node)
                                for node in section_nodes
                            )
                            if section_url
                        ]
                        if _record(section_urls):
                            return True
            return False

        try:
            quick_search = session.get(
                "https://codeofarrules.arkansas.gov/Rules/RuleQuickSearch",
                params={"titleNumber": "1"},
                timeout=25,
                headers=headers,
            )
            quick_search.raise_for_status()
            quick_search_urls = _candidate_arkansas_rule_urls_from_html(
                html=quick_search.text,
                page_url=str(quick_search.url or "https://codeofarrules.arkansas.gov/Rules/Search"),
                limit=max(limit_n * 2, 12),
            )
            direct_quick_search_urls = [
                candidate_url
                for candidate_url in quick_search_urls
                if _is_pdf_candidate_url(candidate_url)
                or _arkansas_rule_level_from_url(candidate_url) == "section"
            ]
            if _record(direct_quick_search_urls):
                return discovered_urls
            _record_arkansas_title_urls(quick_search_urls)
            if seen_title_ids and _expand_title_ids(sorted(seen_title_ids, key=lambda value: int(value))):
                return discovered_urls
            if _expand_title_ids([str(index) for index in range(1, 6)]):
                return discovered_urls
            if discovered_urls:
                return discovered_urls
        except Exception:
            pass

        try:
            search_page = session.get(
                "https://sos-rules-reg.ark.org/rules/search/new",
                timeout=25,
                headers=headers,
            )
            search_page.raise_for_status()
            token_match = re.search(
                r'name=["\']_token["\'][^>]*value=["\']([^"\']+)["\']',
                search_page.text,
                re.IGNORECASE,
            )
            token = str(token_match.group(1) or "").strip() if token_match else ""
            if token:
                for action, payload in (
                    (
                        "https://sos-rules-reg.ark.org/rules/text_search",
                        {"_token": token, "words": "rule"},
                    ),
                    (
                        "https://sos-rules-reg.ark.org/rules/search",
                        {"_token": token, "keywords": "board"},
                    ),
                ):
                    response = session.post(action, data=payload, timeout=25, headers=headers)
                    response.raise_for_status()
                    if _record(
                        _candidate_arkansas_rule_urls_from_html(
                            html=response.text,
                            page_url=str(response.url or action),
                            limit=max(limit_n * 4, 12),
                        ),
                        pdf_only=True,
                    ):
                        return discovered_urls
        except Exception:
            pass

        return discovered_urls

    return await asyncio.to_thread(_run)


def _is_pdf_candidate_url(url: str) -> bool:
    value = str(url or "").strip().lower()
    return value.endswith(".pdf") or ".pdf?" in value


def _is_rtf_candidate_url(url: str) -> bool:
    value = str(url or "").strip().lower()
    return value.endswith(".rtf") or ".rtf?" in value


def _is_docx_candidate_url(url: str) -> bool:
    value = str(url or "").strip().lower()
    return value.endswith(".docx") or ".docx?" in value


def _utah_rule_reference_from_url(url: str) -> str:
    parsed = urlparse(str(url or "").strip())
    path = unquote(parsed.path or "")
    match = re.search(r"/public/rule/([^/]+)/", path, re.IGNORECASE)
    if not match:
        return ""
    return str(match.group(1) or "").strip().upper()


def _utah_rule_type_from_url(url: str) -> str:
    parsed = urlparse(str(url or "").strip())
    path = unquote(parsed.path or "")
    match = re.search(r"/public/rule/[^/]+/([^/?#]+)", path, re.IGNORECASE)
    if not match:
        return "Current Rules"
    value = str(match.group(1) or "").replace("%20", " ").replace("+", " ").strip()
    return value or "Current Rules"


def _utah_rule_detail_cache_key(url: str) -> str:
    parsed = urlparse(str(url or "").strip())
    return parsed._replace(query="", fragment="").geturl().lower().rstrip("/")


def _cache_utah_rule_detail_metadata(url: str, rule: Dict[str, Any]) -> None:
    cache_key = _utah_rule_detail_cache_key(url)
    if not cache_key or not isinstance(rule, dict):
        return
    _UTAH_RULE_DETAIL_METADATA_CACHE[cache_key] = dict(rule)


def _get_cached_utah_rule_detail_metadata(url: str) -> Optional[Dict[str, Any]]:
    cache_key = _utah_rule_detail_cache_key(url)
    if not cache_key:
        return None
    cached_rule = _UTAH_RULE_DETAIL_METADATA_CACHE.get(cache_key)
    if not isinstance(cached_rule, dict):
        return None
    return dict(cached_rule)


def _extract_text_from_downloaded_html_document(document_html: str) -> str:
    value = str(document_html or "")
    if not value:
        return ""

    body_match = re.search(r"<body\b[^>]*>(.*?)</body>", value, re.IGNORECASE | re.DOTALL)
    if body_match:
        value = body_match.group(1)

    value = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", " ", value, flags=re.IGNORECASE | re.DOTALL)
    value = re.sub(r"<[^>]+>", "\n", value)
    value = unescape(value).replace("\ufeff", " ")

    lines = []
    for raw_line in value.splitlines():
        cleaned = re.sub(r"\s+", " ", raw_line).strip()
        if cleaned:
            lines.append(cleaned)
    return "\n".join(lines).strip()


def _montana_collection_uuid_from_url(url: str) -> str:
    parsed = urlparse(str(url or "").strip())
    if parsed.netloc.lower() != "rules.mt.gov":
        return ""
    for pattern in (_MT_POLICY_PATH_RE, _MT_SECTION_PATH_RE, _MT_COLLECTION_PATH_RE):
        match = pattern.fullmatch(parsed.path or "")
        if match:
            return str(match.group("collection") or "").strip()
    return ""


def _montana_section_uuid_from_url(url: str) -> str:
    parsed = urlparse(str(url or "").strip())
    if parsed.netloc.lower() != "rules.mt.gov":
        return ""
    match = _MT_SECTION_PATH_RE.fullmatch(parsed.path or "")
    if not match:
        return ""
    return str(match.group("section") or "").strip()


def _montana_policy_uuid_from_url(url: str) -> str:
    parsed = urlparse(str(url or "").strip())
    if parsed.netloc.lower() != "rules.mt.gov":
        return ""
    match = _MT_POLICY_PATH_RE.fullmatch(parsed.path or "")
    if not match:
        return ""
    return str(match.group("policy") or "").strip()


def _montana_policy_browse_url(collection_uuid: str, policy_uuid: str) -> str:
    return (
        "https://rules.mt.gov/browse/collections/"
        f"{quote(str(collection_uuid or '').strip(), safe='-')}/policies/{quote(str(policy_uuid or '').strip(), safe='-')}"
    )


def _is_montana_inventory_candidate_url(url: str) -> bool:
    parsed = urlparse(str(url or "").strip())
    host = parsed.netloc.lower()
    path = (parsed.path or "").rstrip("/") or "/"
    if host in {"sosmt.gov", "www.sosmt.gov", "legislature.mt.gov", "www.legislature.mt.gov"}:
        return True
    if host != "rules.mt.gov":
        return False
    if _montana_policy_uuid_from_url(url):
        return False
    if _montana_collection_uuid_from_url(url):
        return True
    return path == "/"


def _montana_public_api_headers(*, referer: str = "https://rules.mt.gov/") -> Dict[str, str]:
    return {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json, text/plain, */*",
        "Referer": referer,
    }


def _montana_field_lines(fields: Any) -> List[str]:
    out: List[str] = []
    for field in fields or []:
        if not isinstance(field, dict):
            continue
        label = str(field.get("label") or field.get("key") or "").strip()
        value = str(field.get("value") or "").strip()
        if not label or not value:
            continue
        line = f"{label}: {value}"
        if line not in out:
            out.append(line)
    return out


def _montana_name_looks_repealed(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return "repealed" in text or "revoked" in text


def _ordered_montana_child_sections(children: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(
        children,
        key=lambda child: (
            _montana_name_looks_repealed(child.get("name")),
            str(child.get("sectionId") or ""),
            str(child.get("name") or ""),
        ),
    )


def _ordered_montana_child_policies(policies: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    def _policy_key(policy: Dict[str, Any]) -> tuple[Any, ...]:
        effective_status = str(policy.get("effectiveStatus") or "").strip().upper()
        substatuses = {
            str(value or "").strip().upper()
            for value in (policy.get("substatuses") or [])
            if str(value or "").strip()
        }
        has_bad_substatus = bool(substatuses & {"REVOKED", "REPEALED", "TRANSFERRED", "SUPERSEDED", "EXPIRED"})
        return (
            effective_status != "EFFECTIVE",
            has_bad_substatus,
            _montana_name_looks_repealed(policy.get("name")),
            str(policy.get("sectionId") or policy.get("name") or ""),
        )

    return sorted(policies, key=_policy_key)


async def _discover_montana_rule_document_urls(url: str, *, limit: int = 8) -> List[str]:
    url_value = str(url or "").strip()
    collection_uuid = _montana_collection_uuid_from_url(url_value)
    if not collection_uuid:
        return []
    if _montana_policy_uuid_from_url(url_value):
        return [url_value]

    section_uuid = _montana_section_uuid_from_url(url_value)
    limit_n = max(1, int(limit or 1))

    def _run() -> List[str]:
        out: List[str] = []
        seen_policies: set[str] = set()
        seen_sections: set[str] = set()
        pending_sections: List[Optional[str]] = [section_uuid or None]
        requests_made = 0

        while pending_sections and len(out) < limit_n and requests_made < max(12, limit_n * 6):
            current_section = pending_sections.pop(0)
            if current_section:
                if current_section in seen_sections:
                    continue
                seen_sections.add(current_section)
                api_url = (
                    f"{_MT_PUBLIC_API_BASE_URL}/collections/{collection_uuid}/sections/{current_section}"
                )
            else:
                api_url = f"{_MT_PUBLIC_API_BASE_URL}/collections/{collection_uuid}"
            requests_made += 1
            try:
                response = requests.get(
                    api_url,
                    timeout=25,
                    headers=_montana_public_api_headers(referer=url_value or "https://rules.mt.gov/"),
                )
                response.raise_for_status()
                payload = response.json()
            except Exception:
                continue
            if not isinstance(payload, dict):
                continue
            child_sections = _ordered_montana_child_sections(
                [
                    child
                    for child in (payload.get("childSections") or [])
                    if isinstance(child, dict)
                ]
            )
            child_policies = _ordered_montana_child_policies(
                [
                    policy
                    for policy in (payload.get("childPolicies") or [])
                    if isinstance(policy, dict)
                ]
            )
            if current_section is None and child_sections:
                for child in child_sections:
                    child_uuid = str(child.get("uuid") or "").strip()
                    if not child_uuid or child_uuid in seen_sections:
                        continue
                    pending_sections.append(child_uuid)
                continue
            for policy in child_policies:
                policy_uuid = str(policy.get("uuid") or "").strip()
                if not policy_uuid or policy_uuid in seen_policies:
                    continue
                seen_policies.add(policy_uuid)
                out.append(_montana_policy_browse_url(collection_uuid, policy_uuid))
                if len(out) >= limit_n:
                    break
            if len(out) >= limit_n:
                break
            for child in child_sections:
                child_uuid = str(child.get("uuid") or "").strip()
                if not child_uuid or child_uuid in seen_sections:
                    continue
                pending_sections.append(child_uuid)
        return out

    return await asyncio.to_thread(_run)


async def _scrape_wyoming_rule_detail_via_ajax(url: str) -> Optional[Any]:
    parsed = urlparse(str(url or "").strip())
    host = parsed.netloc.lower()
    path = (parsed.path or "").lower()
    if host != "rules.wyo.gov" or path != "/ajaxhandler.ashx":
        return None

    query = parse_qs(parsed.query or "")
    handler = str((query.get("handler") or [""])[0]).strip()
    handler_key = handler.lower()
    if handler_key not in {"search_getprogramrules", "getruleversionhtml"}:
        return None

    if handler_key == "search_getprogramrules":
        program_id = str((query.get("PROGRAM_ID") or [""])[0]).strip()
        if not program_id:
            return None
        payload = {
            "PROGRAM_ID": program_id,
            "KEYWORD": "",
            "CURRENT_YN": "Y",
            "PROPOSED_YN": "N",
            "EMERGENCY_YN": "N",
            "SUPERCEDED_YN": "N",
            "REPEALED_YN": "Y",
            "EXPIRED_YN": "N",
            "CHAPTER_NUM": "",
            "REF_NUM": "",
            "MODE": str((query.get("MODE") or ["7"])[0]).strip() or "7",
            "DATE_START": "",
            "DATE_END": "",
        }
        method_name = "wyoming_rules_ajax_program"
        fallback_title = f"Wyoming Administrative Rules Program {program_id}"
    else:
        rule_version_id = str((query.get("RULE_VERSION_ID") or [""])[0]).strip()
        if not rule_version_id:
            return None
        payload = {"RULE_VERSION_ID": rule_version_id}
        method_name = "wyoming_rules_ajax_viewer"
        fallback_title = f"Wyoming Administrative Rule {rule_version_id}"

    try:
        response = requests.post(
            f"https://rules.wyo.gov/AjaxHandler.ashx?handler={handler}",
            data=payload,
            timeout=35,
            headers={
                "User-Agent": "Mozilla/5.0",
                "X-Requested-With": "XMLHttpRequest",
            },
        )
    except Exception:
        return None

    if int(getattr(response, "status_code", 599) or 599) >= 400:
        return None

    html = str(getattr(response, "text", "") or "")
    if not html:
        return None
    if _looks_like_browser_challenge(
        status_code=int(getattr(response, "status_code", 200) or 200),
        content_type=str(getattr(response, "headers", {}).get("content-type") or "text/html"),
        head=html[:1024],
    ):
        return None

    chapter_match = re.search(r'class=["\'][^"\']*\brule_viewer_chapter\b[^"\']*["\'][^>]*>(.*?)</', html, re.IGNORECASE | re.DOTALL)
    agency_match = re.search(r'class=["\'][^"\']*\brule_viewer_agency\b[^"\']*["\'][^>]*>(.*?)</', html, re.IGNORECASE | re.DOTALL)
    chapter_title = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", chapter_match.group(1) if chapter_match else "")).strip()
    agency_title = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", agency_match.group(1) if agency_match else "")).strip()
    if chapter_title and agency_title:
        title = f"{chapter_title} - {agency_title}"
    else:
        title = chapter_title or agency_title or fallback_title

    text = _extract_text_from_downloaded_html_document(html)
    if not text:
        return None

    return SimpleNamespace(
        url=url,
        title=title,
        text=text,
        html=html,
        links=[],
        success=True,
        method_used=method_name,
        extraction_provenance={"method": method_name},
    )


async def _scrape_georgia_rule_detail_via_ajax(url: str) -> Optional[Any]:
    parsed = urlparse(str(url or "").strip())
    host = parsed.netloc.lower()
    path = parsed.path or ""
    if host != "rules.sos.ga.gov" or not _GA_GAC_RULE_PATH_RE.fullmatch(path):
        return None

    session = requests.Session()
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": url,
        "X-Requested-With": "XMLHttpRequest",
    }

    try:
        shell_response = session.get(url, timeout=25, headers=headers)
        shell_response.raise_for_status()
    except Exception:
        return None

    shell_html = str(getattr(shell_response, "text", "") or "")
    if not shell_html:
        return None

    try:
        ajax_response = session.post(
            "https://rules.sos.ga.gov/loadthedata.aspx",
            timeout=25,
            headers=headers,
        )
        ajax_response.raise_for_status()
    except Exception:
        return None

    ajax_html = str(getattr(ajax_response, "text", "") or "")
    if not ajax_html:
        return None

    text = _extract_text_from_downloaded_html_document(ajax_html)
    if not text:
        return None

    title = ""
    heading_match = re.search(r"<h2[^>]*>(.*?)</h2>", ajax_html, re.IGNORECASE | re.DOTALL)
    if heading_match:
        title = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", heading_match.group(1))).strip()
    if not title:
        title_match = re.search(r"<title[^>]*>([^<]+)</title>", shell_html, re.IGNORECASE)
        if title_match:
            title = unescape(title_match.group(1)).strip()
    if not title:
        title = f"Georgia Administrative Rule {path.rsplit('/', 1)[-1]}"

    return SimpleNamespace(
        url=url,
        title=title,
        text=text,
        html=ajax_html,
        links=[],
        success=True,
        method_used="georgia_rules_ajax",
        extraction_provenance={"method": "georgia_rules_ajax"},
    )


async def _scrape_montana_rule_detail_via_api(url: str) -> Optional[Any]:
    collection_uuid = _montana_collection_uuid_from_url(url)
    policy_uuid = _montana_policy_uuid_from_url(url)
    if not collection_uuid or not policy_uuid:
        return None

    def _run() -> Optional[Dict[str, Any]]:
        try:
            response = requests.get(
                f"{_MT_PUBLIC_API_BASE_URL}/collections/{collection_uuid}/policies/{policy_uuid}",
                timeout=30,
                headers=_montana_public_api_headers(referer=url),
            )
            response.raise_for_status()
            payload = response.json()
        except Exception:
            return None

        policy = (payload or {}).get("policy") or {}
        if not isinstance(policy, dict):
            return None

        policy_versions = [version for version in (policy.get("policyVersions") or []) if isinstance(version, dict)]
        current_version_uuid = str(policy.get("currentVersionUuid") or "").strip()
        selected_version: Optional[Dict[str, Any]] = None
        if current_version_uuid:
            for version in policy_versions:
                if str(version.get("uuid") or "").strip() == current_version_uuid:
                    selected_version = version
                    break
        if selected_version is None:
            for version in policy_versions:
                if bool(version.get("isActive")):
                    selected_version = version
                    break
        if selected_version is None and policy_versions:
            selected_version = policy_versions[0]

        citation_id = str(policy.get("citationId") or "").strip()
        name = str(policy.get("name") or "").strip()
        title = f"{citation_id} {name}".strip() or name or citation_id

        html = ""
        text = ""
        preview_pdf_url = ""
        for doc_key in ("accessibleHtmlDocument", "previewDocument", "originalDocument"):
            document = dict((selected_version or {}).get(doc_key) or {})
            content_url = str(document.get("contentUrl") or "").strip()
            content_type = str(document.get("contentType") or "").strip().lower()
            if not content_url:
                continue
            absolute_content_url = urljoin("https://rules.mt.gov/", content_url)
            if content_type.startswith("text/html"):
                try:
                    content_response = requests.get(
                        absolute_content_url,
                        timeout=30,
                        headers={
                            **_montana_public_api_headers(referer=url),
                            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                        },
                    )
                    content_response.raise_for_status()
                    html = str(content_response.text or "")
                    text = _extract_text_from_downloaded_html_document(html)
                except Exception:
                    html = ""
                    text = ""
                if text:
                    break
            if not preview_pdf_url and "pdf" in content_type:
                preview_pdf_url = absolute_content_url

        return {
            "title": title,
            "text": text,
            "html": html,
            "preview_pdf_url": preview_pdf_url,
            "policy_fields": _montana_field_lines(policy.get("fields") or []),
            "version_fields": _montana_field_lines((selected_version or {}).get("fields") or []),
            "substatuses": [str(value).strip() for value in ((selected_version or {}).get("subStatuses") or []) if str(value).strip()],
        }

    result = await asyncio.to_thread(_run)
    if not isinstance(result, dict):
        return None

    text = str(result.get("text") or "").strip()
    html = str(result.get("html") or "")
    preview_pdf_url = str(result.get("preview_pdf_url") or "").strip()
    if not text and preview_pdf_url:
        try:
            pdf_response = await asyncio.to_thread(
                requests.get,
                preview_pdf_url,
                timeout=30,
                headers={
                    **_montana_public_api_headers(referer=url),
                    "Accept": "application/pdf,*/*",
                },
            )
            pdf_response.raise_for_status()
            text = await _extract_text_from_pdf_bytes_with_processor(
                bytes(getattr(pdf_response, "content", b"") or b""),
                source_url=preview_pdf_url,
            )
        except Exception:
            text = ""

    extra_lines: List[str] = []
    title = str(result.get("title") or "").strip()
    if title:
        extra_lines.append(title)
    for line in result.get("policy_fields") or []:
        value = str(line or "").strip()
        if value and value not in extra_lines:
            extra_lines.append(value)
    for line in result.get("version_fields") or []:
        value = str(line or "").strip()
        if value and value not in extra_lines:
            extra_lines.append(value)
    substatuses = [value for value in (result.get("substatuses") or []) if str(value or "").strip()]
    if substatuses:
        extra_lines.append(f"Status: {', '.join(substatuses)}")

    extra_text = "\n".join(extra_lines).strip()
    combined_text = "\n\n".join(part for part in (text, extra_text) if str(part or "").strip()).strip()
    if not combined_text:
        return None

    return SimpleNamespace(
        url=url,
        title=title,
        text=combined_text,
        html=html,
        links=[],
        success=True,
        method_used="montana_public_policy_api",
        extraction_provenance={"method": "montana_public_policy_api"},
    )


async def _discover_vermont_lexis_document_urls(*, seed_urls: List[str], limit: int = 8) -> List[str]:
    relevant_seed_urls = [
        str(url or "").strip()
        for url in list(seed_urls or [])
        if urlparse(str(url or "").strip()).netloc.lower() in {"lexisnexis.com", "www.lexisnexis.com", "advance.lexis.com"}
    ]
    if not relevant_seed_urls:
        return []

    limit_n = max(1, int(limit))
    target_url = next(
        (
            url
            for url in relevant_seed_urls
            if _VT_LEXIS_TOC_PATH_RE.fullmatch(urlparse(url).path or "")
        ),
        relevant_seed_urls[0],
    )
    discovered_rule_urls: List[str] = []
    seen_rule_keys: set[str] = set()
    expanded_node_ids: set[str] = set()
    max_expand = max(6, min(36, limit_n * 6))

    try:
        from playwright.async_api import TimeoutError as PlaywrightTimeoutError
        from playwright.async_api import async_playwright
    except Exception:
        return []

    browser_user_agent = _pdf_request_headers(target_url).get("User-Agent") or (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )

    async def _load_page(page: Any, start_url: str) -> None:
        await page.goto(start_url, wait_until="domcontentloaded", timeout=120000)
        try:
            await page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass
        try:
            await page.wait_for_selector("li.js-node", timeout=15000)
        except Exception:
            pass
        await page.wait_for_timeout(750)

    async def _visible_nodes(page: Any) -> List[Dict[str, Any]]:
        return list(
            await page.evaluate(
                """
                () => Array.from(document.querySelectorAll('li.js-node')).map((el, index) => ({
                  ordinal: index,
                  nodeid: el.getAttribute('data-nodeid') || '',
                  nodepath: el.getAttribute('data-nodepath') || '',
                  level: el.getAttribute('data-level') || '',
                  title: el.getAttribute('data-title') || '',
                  haschildren: el.getAttribute('data-haschildren') || '',
                  populated: el.getAttribute('data-populated') || '',
                  docfullpath: el.getAttribute('data-docfullpath') || '',
                  expanded: el.getAttribute('aria-expanded') || ''
                }))
                """
            )
            or []
        )

    async def _expand_node(page: Any, node_id: str) -> bool:
        if not node_id:
            return False
        locator = page.locator(f'li.js-node[data-nodeid="{node_id}"] button.toc-tree__toggle-expansion').first
        try:
            if await locator.count() == 0:
                return False
            await locator.scroll_into_view_if_needed(timeout=3000)
            await locator.click(timeout=5000)
            await page.wait_for_timeout(900)
            return True
        except PlaywrightTimeoutError:
            return False
        except Exception:
            return False

    async with async_playwright() as p:
        browser = None
        context = None
        try:
            if _use_persistent_playwright_profile():
                profile_dir = _playwright_persistent_profile_dir()
                profile_dir.mkdir(parents=True, exist_ok=True)
                context = await p.chromium.launch_persistent_context(
                    str(profile_dir),
                    headless=_playwright_headless_enabled(),
                    user_agent=browser_user_agent,
                )
                page = await context.new_page()
            else:
                browser = await p.chromium.launch(headless=_playwright_headless_enabled())
                context = await browser.new_context(user_agent=browser_user_agent)
                page = await context.new_page()

            await _apply_playwright_session_state(context, page, target_url)
            await _load_page(page, target_url)

            expand_attempts = 0
            while len(discovered_rule_urls) < limit_n and expand_attempts < max_expand:
                nodes = await _visible_nodes(page)
                if not nodes:
                    break

                for node in nodes:
                    docfullpath = str(node.get("docfullpath") or "").strip()
                    if not docfullpath:
                        continue
                    candidate_url = urljoin("https://advance.lexis.com", docfullpath)
                    if not _VT_LEXIS_DOC_PATH_RE.fullmatch(urlparse(candidate_url).path or ""):
                        continue
                    candidate_key = _url_key(candidate_url)
                    if not candidate_key or candidate_key in seen_rule_keys:
                        continue
                    seen_rule_keys.add(candidate_key)
                    discovered_rule_urls.append(candidate_url)
                    if len(discovered_rule_urls) >= limit_n:
                        break
                if len(discovered_rule_urls) >= limit_n:
                    break

                expandable_nodes = [
                    node
                    for node in nodes
                    if str(node.get("haschildren") or "").lower() == "true"
                    and str(node.get("expanded") or "").lower() != "true"
                    and str(node.get("nodeid") or "") not in expanded_node_ids
                ]
                if not expandable_nodes:
                    break

                expandable_nodes.sort(
                    key=lambda node: (
                        -int(str(node.get("level") or "0") or 0),
                        int(node.get("ordinal") or 0),
                    )
                )
                next_node_id = str(expandable_nodes[0].get("nodeid") or "").strip()
                if not next_node_id:
                    break
                expanded_node_ids.add(next_node_id)
                if not await _expand_node(page, next_node_id):
                    continue
                expand_attempts += 1

            return discovered_rule_urls
        finally:
            if context is not None:
                await context.close()
            elif browser is not None:
                await browser.close()


async def _discover_vermont_rule_document_urls(*, seed_urls: List[str], limit: int = 8) -> List[str]:
    relevant_seed_urls = [
        str(url or "").strip()
        for url in list(seed_urls or [])
        if urlparse(str(url or "").strip()).netloc.lower() in {"secure.vermont.gov", "sos.vermont.gov"}
    ]
    if not relevant_seed_urls:
        return []

    def _run() -> List[str]:
        discovered_urls: List[str] = []
        seen_keys: set[str] = set()
        limit_n = max(1, int(limit))

        def _append(candidate_url: str) -> bool:
            normalized_url = str(candidate_url or "").strip()
            if not normalized_url:
                return False
            if not _is_immediate_direct_detail_candidate_url(normalized_url):
                return False
            candidate_key = _url_key(normalized_url)
            if not candidate_key or candidate_key in seen_keys:
                return False
            seen_keys.add(candidate_key)
            discovered_urls.append(normalized_url)
            return True

        fetch_urls: List[str] = []
        rss_url = "https://secure.vermont.gov/SOS/rules/rssFeed.php"
        fetch_urls.append(rss_url)
        for seed_url in relevant_seed_urls:
            parsed_seed = urlparse(seed_url)
            if parsed_seed.netloc.lower() == "secure.vermont.gov" and seed_url not in fetch_urls:
                fetch_urls.append(seed_url)

        for fetch_url in fetch_urls:
            try:
                response = requests.get(
                    fetch_url,
                    timeout=20,
                    headers=_pdf_request_headers(fetch_url),
                )
                response.raise_for_status()
            except Exception:
                continue

            body = str(getattr(response, "text", "") or "")
            if not body:
                continue

            content_type = str(getattr(response, "headers", {}).get("Content-Type", "") or "")
            if "xml" in content_type.lower() or body.lstrip().startswith("<rss"):
                try:
                    root = ET.fromstring(body)
                except ET.ParseError:
                    root = None
                if root is not None:
                    for item in root.findall("./channel/item"):
                        for tag_name in ("link", "guid"):
                            tag = item.find(tag_name)
                            if tag is None:
                                continue
                            if _append(str(tag.text or "")) and len(discovered_urls) >= limit_n:
                                return discovered_urls

            for match in re.findall(
                r"https://secure\.vermont\.gov/SOS/rules/display\.php\?r=\d+",
                body,
                re.IGNORECASE,
            ):
                if _append(match) and len(discovered_urls) >= limit_n:
                    return discovered_urls

        return discovered_urls

    return await asyncio.to_thread(_run)


def _scrape_vermont_lexis_document_candidate(url: str) -> Optional[Any]:
    parsed = urlparse(str(url or "").strip())
    if parsed.netloc.lower() != "advance.lexis.com":
        return None
    if not _VT_LEXIS_DOC_PATH_RE.fullmatch(parsed.path or ""):
        return None

    try:
        response = requests.get(
            url,
            timeout=10,
            headers=_pdf_request_headers(url),
            allow_redirects=True,
        )
        final_url = str(getattr(response, "url", "") or url)
        final_text = response.text or ""
        title_match = re.search(r"<title[^>]*>(.*?)</title>", final_text, re.IGNORECASE | re.DOTALL)
        title = re.sub(r"\s+", " ", title_match.group(1)).strip()[:240] if title_match else ""
        return SimpleNamespace(
            text=final_text,
            html=final_text,
            title=title,
            links=[],
            success=bool(response.ok),
            status_code=int(getattr(response, "status_code", 200) or 200),
            url=final_url,
        )
    except Exception:
        return None


async def _discover_texas_rule_document_urls(*, seed_urls: List[str], limit: int = 8) -> List[str]:
    relevant_seed_urls = [
        str(url or "").strip()
        for url in list(seed_urls or [])
        if urlparse(str(url or "").strip()).netloc.lower() == "texas-sos.appianportalsgov.com"
        and (urlparse(str(url or "").strip()).path or "").lower() == "/rules-and-meetings"
    ]
    if not relevant_seed_urls:
        return []

    limit_n = max(1, int(limit))
    base_url = "https://texas-sos.appianportalsgov.com/rules-and-meetings?interface=VIEW_TAC"
    discovered_rule_urls: List[str] = []
    seen_rule_keys: set[str] = set()

    try:
        from playwright.async_api import async_playwright
    except Exception:
        return []

    browser_user_agent = _pdf_request_headers(base_url).get("User-Agent") or (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )

    def _dedupe(values: List[str]) -> List[str]:
        out: List[str] = []
        seen: set[str] = set()
        for value in values:
            normalized = str(value or "").strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            out.append(normalized)
        return out

    def _collect_regex_values(pattern: str, text: str, *, upper: bool = False) -> List[str]:
        matches = [str(match or "").strip() for match in re.findall(pattern, str(text or ""), re.IGNORECASE)]
        if upper:
            matches = [match.upper() for match in matches]
        return _dedupe(matches)

    def _collect_query_values(html: str, key: str, *, upper: bool = False) -> List[str]:
        pattern = rf"[?&]{re.escape(key)}=([^&#\"'\s>]+)"
        matches = [unquote(str(match or "").strip()) for match in re.findall(pattern, str(html or ""), re.IGNORECASE)]
        if upper:
            matches = [match.upper() for match in matches]
        return _dedupe(matches)

    def _maybe_add_rule_urls(page_url: str, html: str) -> None:
        for candidate_url in _candidate_texas_rule_urls_from_html(
            html=html,
            page_url=page_url,
            limit=max(limit_n * 3, 12),
        ):
            if not _is_direct_detail_candidate_url(candidate_url):
                continue
            candidate_key = _url_key(candidate_url)
            if not candidate_key or candidate_key in seen_rule_keys:
                continue
            seen_rule_keys.add(candidate_key)
            discovered_rule_urls.append(candidate_url)
            if len(discovered_rule_urls) >= limit_n:
                break

    async def _load_page(page: Any, target_url: str) -> tuple[str, str, str]:
        await page.goto(target_url, wait_until="domcontentloaded", timeout=120000)
        try:
            await page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass
        await page.wait_for_timeout(750)
        try:
            text = str(await page.locator("body").inner_text() or "")
        except Exception:
            text = ""
        try:
            html = str(await page.content() or "")
        except Exception:
            html = ""
        return str(page.url or target_url), text, html

    async with async_playwright() as p:
        browser = None
        context = None
        try:
            if _use_persistent_playwright_profile():
                profile_dir = _playwright_persistent_profile_dir()
                profile_dir.mkdir(parents=True, exist_ok=True)
                context = await p.chromium.launch_persistent_context(
                    str(profile_dir),
                    headless=_playwright_headless_enabled(),
                    user_agent=browser_user_agent,
                )
                page = await context.new_page()
            else:
                browser = await p.chromium.launch(headless=_playwright_headless_enabled())
                context = await browser.new_context(user_agent=browser_user_agent)
                page = await context.new_page()

            await _apply_playwright_session_state(context, page, base_url)
            current_url, current_text, current_html = await _load_page(page, relevant_seed_urls[0] or base_url)
            _maybe_add_rule_urls(current_url, current_html)
            if len(discovered_rule_urls) >= limit_n:
                return discovered_rule_urls

            title_ids = _dedupe(
                _collect_regex_values(r"\bTitle\s+(\d{1,3})\b", current_text)
                + _collect_query_values(current_html, "title")
            )
            for title_id in title_ids[: min(3, limit_n)]:
                title_url = f"{base_url}&title={quote(title_id, safe='')}"
                current_url, current_text, current_html = await _load_page(page, title_url)
                _maybe_add_rule_urls(current_url, current_html)
                if len(discovered_rule_urls) >= limit_n:
                    break

                part_ids = _dedupe(
                    _collect_regex_values(r"\bPart\s+(\d{1,3})\b", current_text)
                    + _collect_query_values(current_html, "part")
                )
                for part_id in part_ids[: min(3, limit_n)]:
                    part_url = f"{base_url}&title={quote(title_id, safe='')}&part={quote(part_id, safe='')}"
                    current_url, current_text, current_html = await _load_page(page, part_url)
                    _maybe_add_rule_urls(current_url, current_html)
                    if len(discovered_rule_urls) >= limit_n:
                        break

                    chapter_ids = _dedupe(
                        _collect_regex_values(r"\bChapter\s+(\d{1,4})\b", current_text)
                        + _collect_query_values(current_html, "chapter")
                    )
                    for chapter_id in chapter_ids[: min(3, limit_n)]:
                        chapter_url = (
                            f"{base_url}&title={quote(title_id, safe='')}&part={quote(part_id, safe='')}"
                            f"&chapter={quote(chapter_id, safe='')}"
                        )
                        current_url, current_text, current_html = await _load_page(page, chapter_url)
                        _maybe_add_rule_urls(current_url, current_html)
                        if len(discovered_rule_urls) >= limit_n:
                            break

                        subchapter_ids = _dedupe(
                            _collect_regex_values(r"\bSubchapter\s+([A-Z0-9]{1,4})\b", current_text, upper=True)
                            + _collect_query_values(current_html, "subchapter", upper=True)
                        )
                        for subchapter_id in subchapter_ids[: min(3, limit_n)]:
                            subchapter_url = (
                                f"{base_url}&title={quote(title_id, safe='')}&part={quote(part_id, safe='')}"
                                f"&chapter={quote(chapter_id, safe='')}&subchapter={quote(subchapter_id, safe='')}"
                            )
                            current_url, current_text, current_html = await _load_page(page, subchapter_url)
                            _maybe_add_rule_urls(current_url, current_html)
                            if len(discovered_rule_urls) >= limit_n:
                                break
                        if len(discovered_rule_urls) >= limit_n:
                            break
                    if len(discovered_rule_urls) >= limit_n:
                        break
                if len(discovered_rule_urls) >= limit_n:
                    break

            return discovered_rule_urls
        finally:
            if context is not None:
                await context.close()
            elif browser is not None:
                await browser.close()


async def _scrape_texas_tac_rule_detail_via_playwright(url: str) -> Optional[SimpleNamespace]:
    parsed = urlparse(str(url or "").strip())
    if parsed.netloc.lower() != "texas-sos.appianportalsgov.com":
        return None
    if (parsed.path or "").lower() != "/rules-and-meetings":
        return None

    query_params = parse_qs(parsed.query or "")
    interface = str((query_params.get("interface") or [""])[0]).strip().upper()
    record_id = str((query_params.get("recordId") or [""])[0]).strip()
    if interface != "VIEW_TAC_SUMMARY" or not record_id.isdigit():
        return None

    try:
        from playwright.async_api import async_playwright
    except Exception:
        return None

    browser_user_agent = _pdf_request_headers(url).get("User-Agent") or (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )

    async with async_playwright() as p:
        browser = None
        context = None
        try:
            if _use_persistent_playwright_profile():
                profile_dir = _playwright_persistent_profile_dir()
                profile_dir.mkdir(parents=True, exist_ok=True)
                context = await p.chromium.launch_persistent_context(
                    str(profile_dir),
                    headless=_playwright_headless_enabled(),
                    user_agent=browser_user_agent,
                )
                page = await context.new_page()
            else:
                browser = await p.chromium.launch(headless=_playwright_headless_enabled())
                context = await browser.new_context(user_agent=browser_user_agent)
                page = await context.new_page()

            await _apply_playwright_session_state(context, page, url)
            await page.goto(url, wait_until="networkidle", timeout=120000)
            try:
                await page.wait_for_selector("iframe", timeout=10000)
            except Exception:
                pass
            await page.wait_for_timeout(1000)

            main_text = str(await page.locator("body").inner_text() or "").strip()
            frame_texts: List[str] = []
            for frame in page.frames[1:]:
                try:
                    frame_text = str(await frame.locator("body").inner_text(timeout=5000) or "").strip()
                except Exception:
                    frame_text = ""
                if len(frame_text) < 40:
                    continue
                if frame_text not in frame_texts:
                    frame_texts.append(frame_text)

            if not frame_texts:
                return None

            title = ""
            lines = [line.strip() for line in main_text.splitlines() if line.strip()]
            for idx, line in enumerate(lines):
                if re.match(r"^Rule\s+§", line):
                    next_line = lines[idx + 1] if idx + 1 < len(lines) else ""
                    title = " ".join(part for part in (line, next_line) if part).strip()
                    break

            combined_text = "\n\n".join(part for part in ([title] if title else []) + frame_texts if str(part or "").strip())
            if not combined_text:
                return None

            return SimpleNamespace(
                url=url,
                title=title,
                text=combined_text,
                html="",
                links=[],
                success=True,
                method_used="texas_tac_playwright",
                extraction_provenance={"method": "texas_tac_playwright"},
            )
        finally:
            if context is not None:
                await context.close()
            elif browser is not None:
                await browser.close()


def _south_dakota_rule_reference_from_url(url: str) -> str:
    parsed = urlparse(str(url or "").strip())
    host = parsed.netloc.lower()
    if host != "sdlegislature.gov":
        return ""

    detail_match = _SD_RULE_DETAIL_PATH_RE.fullmatch(parsed.path or "")
    if detail_match:
        return str(detail_match.group("rule") or "").strip()

    rule_value = str((parse_qs(parsed.query or "").get("Rule") or [""])[0]).strip()
    if _SD_DISPLAY_RULE_PATH_RE.search(parsed.path or "") and _SD_RULE_REFERENCE_RE.fullmatch(rule_value):
        return rule_value

    api_match = re.search(
        r"/api/Rules(?:/Rule)?/(?P<rule>\d{2}:\d{2}(?::\d{2}){0,3})(?:\.html)?$",
        parsed.path or "",
        re.IGNORECASE,
    )
    if api_match:
        return str(api_match.group("rule") or "").strip()

    return ""


async def _discover_south_dakota_rule_document_urls(*, limit: int = 8) -> List[str]:
    limit_n = max(1, int(limit or 1))

    def _run() -> List[str]:
        request_headers = {
            "Accept": "application/json",
            "Referer": "https://sdlegislature.gov/Rules/Administrative",
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36"
            ),
        }

        def _extract_child_rule_urls(html_text: str) -> List[str]:
            extracted: List[str] = []
            local_seen: set[str] = set()
            for rule_reference in re.findall(
                r"(?:DisplayRule\.aspx\?Rule=|/Rules/Administrative/)(\d{2}:\d{2}(?::\d{2}){1,3})",
                html_text or "",
                re.IGNORECASE,
            ):
                normalized_reference = str(rule_reference or "").strip()
                if not _SD_RULE_REFERENCE_RE.fullmatch(normalized_reference):
                    continue
                rule_url = (
                    "https://sdlegislature.gov/Rules/Administrative/DisplayRule.aspx"
                    f"?Rule={normalized_reference}"
                )
                rule_key = _url_key(rule_url)
                if not rule_key or rule_key in local_seen:
                    continue
                local_seen.add(rule_key)
                extracted.append(rule_url)
            return extracted

        try:
            response = requests.get(
                "https://sdlegislature.gov/api/Rules",
                timeout=25,
                headers=request_headers,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception:
            return []
        if not isinstance(payload, list):
            return []

        direct_rule_urls: List[str] = []
        container_rule_refs: List[str] = []
        seen: set[str] = set()
        excluded_statuses = {"repealed", "reserved", "transferred"}
        for item in payload:
            if not isinstance(item, dict):
                continue
            rule_number = str(item.get("RuleNumber") or "").strip()
            if not _SD_RULE_REFERENCE_RE.fullmatch(rule_number):
                continue
            status_value = str(item.get("Status") or "").strip().lower()
            catchline = str(item.get("Catchline") or "").strip()
            if status_value in excluded_statuses:
                continue
            if catchline.upper() == "RESERVED":
                continue
            rule_url = f"https://sdlegislature.gov/Rules/Administrative/{rule_number}"
            rule_key = _url_key(rule_url)
            if not rule_key or rule_key in seen:
                continue
            seen.add(rule_key)
            if rule_number.count(":") >= 2:
                direct_rule_urls.append(rule_url)
            else:
                container_rule_refs.append(rule_number)

        results: List[str] = direct_rule_urls[:limit_n]
        result_keys = {_url_key(url) for url in results}
        if len(results) >= limit_n:
            return results

        for container_rule_ref in container_rule_refs:
            try:
                container_response = requests.get(
                    f"https://sdlegislature.gov/api/Rules/{container_rule_ref}",
                    timeout=25,
                    headers=request_headers,
                )
                container_response.raise_for_status()
                container_payload = container_response.json()
            except Exception:
                continue
            if not isinstance(container_payload, dict):
                continue
            child_rule_urls = _extract_child_rule_urls(str(container_payload.get("Html") or ""))
            for child_rule_url in child_rule_urls:
                child_rule_key = _url_key(child_rule_url)
                if not child_rule_key or child_rule_key in result_keys:
                    continue
                result_keys.add(child_rule_key)
                results.append(child_rule_url)
                if len(results) >= limit_n:
                    return results

        return results

    return await asyncio.to_thread(_run)


def _alabama_public_code_number_from_url(url: str) -> str:
    parsed = urlparse(str(url or "").strip())
    if parsed.netloc.lower() != "admincode.legislature.state.al.us":
        return ""
    if not _AL_PUBLIC_CODE_PATH_RE.fullmatch(parsed.path or ""):
        return ""
    return str((parse_qs(parsed.query or "").get("number") or [""])[0]).strip()


def _alabama_public_code_url(number: str) -> str:
    return (
        "https://admincode.legislature.state.al.us/administrative-code"
        f"?number={quote(str(number or '').strip(), safe='-.:')}"
    )


def _post_alabama_persisted_query(*, operation_name: str, sha_hash: str, variables: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Referer": "https://admincode.legislature.state.al.us/administrative-code",
    }
    payload = {
        "operationName": operation_name,
        "variables": variables or {},
        "extensions": {"persistedQuery": {"version": 1, "sha256Hash": sha_hash}},
    }
    try:
        response = requests.post(
            _AL_PUBLIC_CODE_GRAPHQL_URL,
            timeout=25,
            headers=headers,
            json=payload,
        )
        response.raise_for_status()
        body = response.json()
    except Exception:
        return None
    if not isinstance(body, dict):
        return None
    if body.get("errors"):
        return None
    data = body.get("data")
    if not isinstance(data, dict):
        return None
    return data


async def _discover_alabama_rule_document_urls(*, limit: int = 8) -> List[str]:
    limit_n = max(1, int(limit or 1))

    def _run() -> List[str]:
        data = _post_alabama_persisted_query(
            operation_name="agencySortTitles",
            sha_hash=_AL_AGENCY_SORT_TITLES_HASH,
        )
        agencies = list((data or {}).get("agencies") or [])
        results: List[str] = []
        seen: set[str] = set()
        for agency in agencies:
            if not isinstance(agency, dict):
                continue
            control_number = str(agency.get("controlNumber") or "").strip()
            if not control_number:
                continue
            agency_data = _post_alabama_persisted_query(
                operation_name="publicCode",
                sha_hash=_AL_PUBLIC_CODE_HASH,
                variables={"number": control_number},
            )
            document = (agency_data or {}).get("document") or {}
            if not isinstance(document, dict) or str(document.get("__typename") or "") != "Agency":
                continue
            for chapter in document.get("chapters") or []:
                if not isinstance(chapter, dict):
                    continue
                for rule in chapter.get("rules") or []:
                    if not isinstance(rule, dict):
                        continue
                    rule_number = str(rule.get("idText") or "").strip()
                    if not _AL_RULE_NUMBER_RE.fullmatch(rule_number):
                        continue
                    rule_url = _alabama_public_code_url(rule_number)
                    rule_key = _url_key(rule_url)
                    if not rule_key or rule_key in seen:
                        continue
                    seen.add(rule_key)
                    results.append(rule_url)
                    if len(results) >= limit_n:
                        return results
        return results

    return await asyncio.to_thread(_run)


def _mississippi_adminsearch_agency_values_from_html(html: str) -> List[str]:
    soup = BeautifulSoup(html or "", "html.parser")
    select = soup.find("select", id="cAgencySearch")
    if select is None:
        return []

    prioritized: List[str] = []
    fallback: List[str] = []
    seen: set[str] = set()
    for option in select.find_all("option"):
        raw_value = str(option.get("value") or "")
        normalized_value = raw_value.strip()
        if not normalized_value or not normalized_value.isdigit() or normalized_value in seen:
            continue
        seen.add(normalized_value)
        label = " ".join(str(option.get_text(" ", strip=True) or "").split())
        if "SECRETARY OF STATE" in label.upper():
            prioritized.append(raw_value)
        else:
            fallback.append(raw_value)
    return prioritized + fallback


def _mississippi_adminsearch_document_urls_from_response(payload: Any, *, limit: int) -> List[str]:
    body = payload if isinstance(payload, dict) else {}
    raw_data = str(body.get("d") or "").strip()
    if not raw_data:
        return []

    record_blob = raw_data.rsplit("|", 1)[0]
    urls: List[str] = []
    seen: set[str] = set()
    for raw_record in record_blob.split("^"):
        record = str(raw_record or "").strip()
        if not record:
            continue
        filename = str(record.split("~")[-1] or "").strip()
        if not filename.lower().endswith(".pdf"):
            continue
        document_url = urljoin(_MS_ADMINSEARCH_DOCUMENT_BASE_URL, quote(filename, safe="-._~"))
        document_key = _url_key(document_url)
        if not document_key or document_key in seen:
            continue
        seen.add(document_key)
        urls.append(document_url)
        if len(urls) >= max(1, int(limit or 1)):
            break
    return urls


async def _discover_mississippi_rule_document_urls(*, limit: int = 8) -> List[str]:
    limit_n = max(1, int(limit or 1))

    def _run() -> List[str]:
        agency_values: List[str] = []
        request_headers = {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": _MS_ADMINSEARCH_INDEX_URL,
        }

        try:
            response = requests.get(
                _MS_ADMINSEARCH_INDEX_URL,
                timeout=25,
                headers=request_headers,
            )
            response.raise_for_status()
            agency_values = _mississippi_adminsearch_agency_values_from_html(str(getattr(response, "text", "") or ""))
        except Exception:
            agency_values = []
        if not agency_values:
            agency_values = list(_MS_ADMINSEARCH_DEFAULT_AGENCY_VALUES)

        results: List[str] = []
        seen: set[str] = set()
        service_headers = {
            "User-Agent": request_headers["User-Agent"],
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Content-Type": "application/json; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "Origin": "https://www.sos.ms.gov",
            "Referer": _MS_ADMINSEARCH_INDEX_URL,
        }
        for agency_value in agency_values:
            payload = {
                "tmpSubject": "",
                "tmpAgency": agency_value,
                "tmpPartRange1": "",
                "tmpPartRange2": "",
                "tmpRuleSum": "",
                "tmpOrder": "PartNo",
                "tmpOrderDirec": "Ascending",
                "tmpSearchDate1": "",
                "tmpSearchDate2": "",
                "tmpDateType": "0",
            }
            try:
                service_response = requests.post(
                    _MS_ADMINSEARCH_SERVICE_URL,
                    timeout=25,
                    headers=service_headers,
                    json=payload,
                )
                service_response.raise_for_status()
                service_payload = service_response.json()
            except Exception:
                continue

            for document_url in _mississippi_adminsearch_document_urls_from_response(service_payload, limit=limit_n):
                document_key = _url_key(document_url)
                if not document_key or document_key in seen:
                    continue
                seen.add(document_key)
                results.append(document_url)
                if len(results) >= limit_n:
                    return results

        return results

    return await asyncio.to_thread(_run)


def _indiana_api_request_headers(*, referer_url: str = "https://iar.iga.in.gov/code/current") -> Dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json,text/plain,*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": referer_url,
        "Origin": "https://iar.iga.in.gov",
        "Sec-Fetch-Site": "cross-site",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
    }


def _indiana_article_identifiers_from_url(url: str) -> tuple[str, str, str]:
    parsed = urlparse(str(url or "").strip())
    if parsed.netloc.lower() != "iar.iga.in.gov":
        return "", "", ""
    match = _INDIANA_ADMIN_CODE_ARTICLE_PATH_RE.fullmatch(parsed.path or "")
    if not match:
        return "", "", ""
    return (
        str(match.group("edition") or "").strip(),
        str(match.group("title_num") or "").strip(),
        str(match.group("article_num") or "").strip(),
    )


def _get_indiana_admin_code_editions_payload() -> List[Dict[str, Any]]:
    try:
        response = requests.get(
            f"{_INDIANA_ADMIN_CODE_API_BASE_URL}/adminCodeEditions",
            timeout=25,
            headers=_indiana_api_request_headers(),
        )
        response.raise_for_status()
        payload = response.json()
    except Exception:
        return []

    edition_list = (payload or {}).get("iar_iac_edition_list") or []
    return [item for item in edition_list if isinstance(item, dict)]


def _candidate_indiana_edition_years(edition_token: str) -> List[int]:
    normalized_token = str(edition_token or "").strip().lower()
    if normalized_token.isdigit():
        return [int(normalized_token)]

    candidate_years: List[int] = []
    for item in _get_indiana_admin_code_editions_payload():
        edition_year = str(item.get("edition_year") or "").strip()
        if edition_year.isdigit():
            candidate_years.append(int(edition_year))

    if not candidate_years:
        current_year = datetime.utcnow().year
        candidate_years = [current_year + 1, current_year, current_year - 1, 2027, 2026, 2025, 2024, 2006]

    ordered_years: List[int] = []
    for year in sorted(candidate_years, reverse=True):
        if year not in ordered_years:
            ordered_years.append(year)
    return ordered_years


async def _discover_indiana_rule_document_urls(*, limit: int = 8) -> List[str]:
    limit_n = max(1, int(limit or 1))

    def _run() -> List[str]:
        results: List[str] = []
        seen: set[str] = set()

        for edition_year in _candidate_indiana_edition_years("current"):
            try:
                response = requests.get(
                    f"{_INDIANA_ADMIN_CODE_API_BASE_URL}/adminCodeTree",
                    params={"edition_year": edition_year, "doc_stage": "public"},
                    timeout=25,
                    headers=_indiana_api_request_headers(),
                )
                response.raise_for_status()
                payload = response.json()
            except Exception:
                continue

            title_list = (payload or {}).get("iar_iac_title_article_list") or []
            if not isinstance(title_list, list):
                continue

            for title_item in title_list:
                if not isinstance(title_item, dict):
                    continue
                title_num = str(title_item.get("title_num") or "").strip()
                if not title_num.isdigit():
                    continue
                for article in title_item.get("article") or []:
                    if not isinstance(article, dict):
                        continue
                    article_num = str(article.get("article_num") or "").strip()
                    article_name = str(article.get("article_name") or "").strip()
                    if not article_num or _INDIANA_NONCURRENT_ARTICLE_RE.search(article_name):
                        continue
                    candidate_url = f"https://iar.iga.in.gov/code/current/{title_num}/{article_num}"
                    candidate_key = _url_key(candidate_url)
                    if not candidate_key or candidate_key in seen:
                        continue
                    seen.add(candidate_key)
                    results.append(candidate_url)
                    if len(results) >= limit_n:
                        return results

            if results:
                return results

        return results

    return await asyncio.to_thread(_run)


async def _scrape_indiana_rule_detail_via_api(url: str) -> Optional[Any]:
    edition_token, title_num, article_num = _indiana_article_identifiers_from_url(url)
    if not title_num or not article_num:
        return None

    def _run() -> Optional[Any]:
        referer_url = f"https://iar.iga.in.gov/code/{edition_token or 'current'}/{title_num}/{article_num}"
        for edition_year in _candidate_indiana_edition_years(edition_token or "current"):
            try:
                response = requests.get(
                    f"{_INDIANA_ADMIN_CODE_API_BASE_URL}/adminCodeArticle",
                    params={
                        "doc_stage": "public",
                        "edition_year": edition_year,
                        "title_num": title_num,
                        "article_num": article_num,
                    },
                    timeout=25,
                    headers=_indiana_api_request_headers(referer_url=referer_url),
                )
                response.raise_for_status()
                payload = response.json()
            except Exception:
                continue

            article_payload = (payload or {}).get("iar_iac_article_doc") or {}
            if not isinstance(article_payload, dict):
                continue

            doc_html = str(article_payload.get("doc_html") or "").strip()
            if not doc_html:
                continue

            text = _extract_text_from_downloaded_html_document(doc_html)
            if not text:
                text = BeautifulSoup(doc_html, "html.parser").get_text("\n", strip=True)
            if not text:
                continue

            title_num_value = str(article_payload.get("title_num") or title_num).strip()
            title_name = str(article_payload.get("title_name") or "").strip()
            article_name = str(article_payload.get("article_name") or "").strip()
            title = ", ".join(
                part
                for part in (
                    " ".join(part for part in (f"Title {title_num_value}", article_name) if part).strip(),
                    title_name or "",
                )
                if part
            ).strip()
            if not title:
                title = f"Title {title_num_value}, Article {article_num}"

            return SimpleNamespace(
                url=url,
                title=title,
                text=text,
                html=doc_html,
                links=[],
                success=True,
                method_used="indiana_admin_code_api",
                extraction_provenance={"method": "indiana_admin_code_api"},
            )

        return None

    return await asyncio.to_thread(_run)


def _oklahoma_public_rule_url(*, title_num: str, section_num: str) -> str:
    return "https://rules.ok.gov/code?" + urlencode(
        {
            "titleNum": str(title_num or "").strip(),
            "sectionNum": str(section_num or "").strip(),
        }
    )


def _candidate_oklahoma_rule_urls_from_text(*, text: str, page_url: str = "", limit: int = 12) -> List[str]:
    body = re.sub(r"\s+", " ", str(text or "")).strip()
    if not body or "oklahoma administrative code" not in body.lower():
        return []

    parsed_page = urlparse(str(page_url or "").strip())
    if parsed_page.netloc.lower() not in {"", "rules.ok.gov"}:
        return []
    if parsed_page.netloc and (parsed_page.path or "").rstrip("/").lower() != "/code":
        return []

    results: List[str] = []
    seen: set[str] = set()
    limit_n = max(1, int(limit or 1))
    title_listing_re = re.compile(
        r"Title\s+(?P<title_num>\d{1,3})\.\s+(?P<title_name>.*?)(?=Title\s+\d{1,3}\.\s+|$)",
        re.IGNORECASE | re.DOTALL,
    )
    for match in title_listing_re.finditer(body):
        title_num = str(match.group("title_num") or "").strip()
        title_name = re.sub(r"\s+", " ", str(match.group("title_name") or "")).strip(" -")
        if not title_num or not title_name:
            continue
        if any(token in title_name.lower() for token in ("abolished", "terminated", "repealed", "reserved")):
            continue
        candidate_url = "https://rules.ok.gov/code?" + urlencode({"titleNum": title_num})
        candidate_key = _url_key(candidate_url)
        if not candidate_key or candidate_key in seen:
            continue
        seen.add(candidate_key)
        results.append(candidate_url)
        if len(results) >= limit_n:
            break
    return results


def _oklahoma_rule_identifiers_from_url(url: str) -> tuple[str, str]:
    parsed = urlparse(str(url or "").strip())
    if parsed.netloc.lower() != "rules.ok.gov" or (parsed.path or "").lower() != "/code":
        return "", ""
    query_params = parse_qs(parsed.query or "")
    title_num = str((query_params.get("titleNum") or [""])[0]).strip()
    section_num = str((query_params.get("sectionNum") or [""])[0]).strip()
    if not title_num:
        return "", ""
    if section_num and not _OK_RULE_SECTION_NUM_RE.fullmatch(section_num):
        return "", ""
    return title_num, section_num


_OKLAHOMA_TITLE_SEGMENTS_CACHE: Dict[str, List[Dict[str, Any]]] = {}


def _get_oklahoma_title_segments_payload(title_num: str) -> List[Dict[str, Any]]:
    normalized_title_num = str(title_num or "").strip()
    if not normalized_title_num.isdigit():
        return []

    cached_payload = _OKLAHOMA_TITLE_SEGMENTS_CACHE.get(normalized_title_num)
    if cached_payload is not None:
        return cached_payload

    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json,text/plain,*/*"}
    try:
        response = requests.get(
            "https://okadminrules-api.azurewebsites.net/GetSegmentsByTitleNum",
            params={"titleNum": normalized_title_num},
            timeout=25,
            headers=headers,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception:
        return []

    normalized_payload = [item for item in payload or [] if isinstance(item, dict)]
    _OKLAHOMA_TITLE_SEGMENTS_CACHE[normalized_title_num] = normalized_payload
    return normalized_payload


async def _discover_oklahoma_rule_document_urls(*, limit: int = 8) -> List[str]:
    limit_n = max(1, int(limit or 1))

    def _run() -> List[str]:
        headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json,text/plain,*/*"}
        try:
            rules_response = requests.get(
                "https://okadminrules-api.azurewebsites.net/GetAllRules",
                params={"pageNumber": 1, "pageSize": max(25, min(limit_n * 10, 200)), "filter": "false"},
                timeout=25,
                headers=headers,
            )
            rules_response.raise_for_status()
            rules_payload = rules_response.json()
        except Exception:
            return []

        results: List[str] = []
        seen: set[str] = set()
        for rule in rules_payload or []:
            if not isinstance(rule, dict):
                continue
            title_num = str(rule.get("referenceCode") or "").strip()
            if not title_num.isdigit():
                continue
            segments_payload = _get_oklahoma_title_segments_payload(title_num)
            if not segments_payload:
                continue

            ranked_segments: List[tuple[int, str]] = []
            for segment in segments_payload or []:
                if not isinstance(segment, dict):
                    continue
                if str(segment.get("name") or "").strip().lower() != "section":
                    continue
                section_num = str(segment.get("sectionNum") or "").strip()
                segment_text = str(segment.get("text") or "").strip()
                if not _OK_RULE_SECTION_NUM_RE.fullmatch(section_num) or not segment_text:
                    continue
                ranked_segments.append(
                    (
                        len(_extract_text_from_downloaded_html_document(segment_text) or segment_text),
                        section_num,
                    )
                )

            for _text_length, section_num in sorted(ranked_segments, key=lambda item: (-item[0], item[1])):
                candidate_url = _oklahoma_public_rule_url(title_num=title_num, section_num=section_num)
                candidate_key = _url_key(candidate_url)
                if not candidate_key or candidate_key in seen:
                    continue
                seen.add(candidate_key)
                results.append(candidate_url)
                if len(results) >= limit_n:
                    return results
        return results

    return await asyncio.to_thread(_run)


async def _discover_michigan_rule_document_urls(*, seed_urls: List[str], limit: int = 8) -> List[str]:
    relevant_seed_urls = [
        url
        for url in seed_urls
        if urlparse(str(url or "").strip()).netloc.lower() == "ars.apps.lara.state.mi.us"
    ]
    if not relevant_seed_urls:
        return []

    limit_n = max(1, int(limit or 1))

    def _run() -> List[str]:
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        results: List[str] = []
        seen: set[str] = set()
        seen_department_pages: set[str] = set()

        def _fetch_text(url: str) -> str:
            response = requests.get(url, timeout=25, headers=headers)
            response.raise_for_status()
            return str(response.text or "")

        def _record_links_from_html(html: str, *, page_url: str) -> bool:
            soup = BeautifulSoup(html or "", "html.parser")
            for anchor in soup.find_all("a", href=True):
                candidate_url = urljoin(page_url, str(anchor.get("href") or "").strip())
                if not _is_direct_detail_candidate_url(candidate_url):
                    continue
                key = _url_key(candidate_url)
                if not key or key in seen:
                    continue
                seen.add(key)
                results.append(candidate_url)
                if len(results) >= limit_n:
                    return True
            return False

        for seed_url in relevant_seed_urls:
            parsed = urlparse(str(seed_url or "").strip())
            normalized_path = (parsed.path or "").rstrip("/").lower() or "/"

            if normalized_path == "/transaction/rfrtransaction":
                try:
                    if _record_links_from_html(_fetch_text(seed_url), page_url=seed_url):
                        return results
                except Exception:
                    pass
                continue

            if normalized_path == "/admincode/deptbureauadmincode":
                try:
                    if _record_links_from_html(_fetch_text(seed_url), page_url=seed_url):
                        return results
                except Exception:
                    pass
                continue

            if normalized_path != "/admincode/admincode":
                continue

            try:
                home_html = _fetch_text(seed_url)
            except Exception:
                continue

            soup = BeautifulSoup(home_html, "html.parser")
            department_values: List[str] = []
            for option in soup.select("select[name='Department'] option"):
                department_value = str(option.get("value") or option.get_text(" ", strip=True) or "").strip()
                if not department_value or department_value.lower().startswith("select department"):
                    continue
                if department_value in department_values:
                    continue
                department_values.append(department_value)

            for department_value in department_values:
                department_page_url = (
                    "https://ars.apps.lara.state.mi.us/AdminCode/DeptBureauAdminCode?"
                    + urlencode({"Department": department_value, "Bureau": "All"})
                )
                page_key = _url_key(department_page_url)
                if not page_key or page_key in seen_department_pages:
                    continue
                seen_department_pages.add(page_key)
                try:
                    if _record_links_from_html(_fetch_text(department_page_url), page_url=department_page_url):
                        return results
                except Exception:
                    continue

        return results

    return await asyncio.to_thread(_run)


async def _discover_alaska_rule_document_urls(*, seed_urls: List[str], limit: int = 8) -> List[str]:
    relevant_seed_urls = [
        url
        for url in seed_urls
        if urlparse(str(url or "").strip()).netloc.lower() in {"www.akleg.gov", "akleg.gov"}
    ]
    if not relevant_seed_urls:
        return []

    limit_n = max(1, int(limit or 1))

    def _run() -> List[str]:
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        results: List[str] = []
        seen: set[str] = set()
        session = requests.Session()

        def _record(section_id: str) -> bool:
            section_value = str(section_id or "").strip()
            if not _AK_AAC_SECTION_PATH_RE.fullmatch(f"/aac/{section_value}"):
                return False
            print_url = (
                "https://www.akleg.gov/basis/aac.asp?"
                + urlencode({"media": "print", "secStart": section_value, "secEnd": section_value})
            )
            key = _url_key(print_url)
            if not key or key in seen:
                return False
            seen.add(key)
            results.append(print_url)
            return len(results) >= limit_n

        for seed_url in relevant_seed_urls:
            parsed = urlparse(str(seed_url or "").strip())
            if (parsed.path or "").lower() != "/basis/aac.asp":
                continue
            try:
                root_html = session.get(seed_url, timeout=25, headers=headers).text
            except Exception:
                continue

            title_ids = [
                match.strip()
                for match in re.findall(r"loadTOC\((?:'|\")\s*(\d+)\s*(?:'|\")\)", root_html)
                if match.strip()
            ]

            for title_id in title_ids:
                try:
                    title_html = session.get(
                        f"https://www.akleg.gov/basis/aac.asp?media=js&type=TOC&title={quote(title_id)}",
                        timeout=25,
                        headers=headers,
                    ).text
                except Exception:
                    continue

                chapter_ids = []
                for chapter_match in re.findall(r"loadTOC\((?:'|\")\s*(\d+\.\d+)\s*(?:'|\")\)", title_html):
                    chapter_value = str(chapter_match or "").strip()
                    if not chapter_value or chapter_value.endswith(".0"):
                        continue
                    if chapter_value in chapter_ids:
                        continue
                    chapter_ids.append(chapter_value)

                for chapter_id in chapter_ids:
                    try:
                        chapter_html = session.get(
                            f"https://www.akleg.gov/basis/aac.asp?media=js&type=TOC&title={quote(chapter_id)}",
                            timeout=25,
                            headers=headers,
                        ).text
                    except Exception:
                        continue

                    for section_id in re.findall(r"checkLink\('([0-9]+\.[0-9]+\.[0-9]+)'\)", chapter_html):
                        if _record(section_id):
                            return results

        return results

    return await asyncio.to_thread(_run)


def _alaska_rule_section_reference_from_url(url: str) -> str:
    parsed = urlparse(str(url or "").strip())
    host = parsed.netloc.lower()
    path = parsed.path or ""

    if host == "akrules.elaws.us" and _AK_AAC_SECTION_PATH_RE.fullmatch(path):
        return path.strip("/").split("/")[-1]

    if host == "www.akleg.gov" and path.lower() == "/basis/aac.asp":
        query_params = parse_qs(parsed.query or "")
        media = str((query_params.get("media") or [""])[0]).strip().lower()
        sec_start = str((query_params.get("secStart") or [""])[0]).strip()
        sec_end = str((query_params.get("secEnd") or [""])[0]).strip()
        if media == "print" and sec_start == sec_end and _AK_AAC_SECTION_PATH_RE.fullmatch(f"/aac/{sec_start}"):
            return sec_start

    return ""


def _alaska_rule_print_view_url(section_reference: str) -> str:
    normalized_reference = str(section_reference or "").strip()
    return "https://www.akleg.gov/basis/aac.asp?" + urlencode(
        {"media": "print", "secStart": normalized_reference, "secEnd": normalized_reference}
    )


async def _scrape_alaska_rule_detail_via_print_view(url: str) -> Optional[Any]:
    section_reference = _alaska_rule_section_reference_from_url(url)
    if not section_reference:
        return None

    def _run() -> Optional[Any]:
        fetch_url = _alaska_rule_print_view_url(section_reference)
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": "https://www.akleg.gov/basis/aac.asp",
        }
        try:
            response = requests.get(fetch_url, timeout=25, headers=headers)
            response.raise_for_status()
            html = str(response.text or "").strip()
        except Exception:
            return None

        if not html:
            return None

        text = _extract_text_from_downloaded_html_document(html)
        if not text:
            text = BeautifulSoup(html, "html.parser").get_text("\n", strip=True)
        if not text:
            return None

        soup = BeautifulSoup(html, "html.parser")
        title = ""
        section_anchor = soup.find("a", attrs={"name": section_reference})
        if section_anchor is not None:
            next_link = section_anchor.find_next("a")
            if next_link is not None:
                title = re.sub(r"\s+", " ", next_link.get_text(" ", strip=True)).strip()

        if not title:
            reference_parts = section_reference.split(".")
            title = f"{reference_parts[0]} AAC {'.'.join(reference_parts[1:])}" if len(reference_parts) >= 3 else section_reference

        return SimpleNamespace(
            url=url,
            title=title,
            text=text,
            html=html,
            links=[],
            success=True,
            method_used="alaska_print_view",
            extraction_provenance={"method": "alaska_print_view", "fetch_url": fetch_url},
        )

    return await asyncio.to_thread(_run)


async def _discover_new_hampshire_archived_rule_document_urls_with_diagnostics(
    *,
    seed_urls: List[str],
    allowed_hosts: Optional[set[str]] = None,
    limit: int = 8,
) -> Dict[str, Any]:
    frontier = [
        _normalize_new_hampshire_archived_wayback_url(url)
        for url in seed_urls
        if "gc.nh.gov/rules/about_rules/listagencies.aspx" in str(url or "").strip().lower()
    ]
    diagnostics: Dict[str, Any] = {
        "frontier_count": len(frontier),
        "pages_attempted": 0,
        "pages_fetched": 0,
        "fetch_attempts": 0,
        "fetch_failures": 0,
        "shell_pages_rejected": 0,
        "capture_candidates_discovered": 0,
        "inventory_pages_enqueued": 0,
        "links_considered": 0,
        "document_urls_found": 0,
    }
    if not frontier:
        diagnostics["reason"] = "no_frontier"
        return {"document_urls": [], "diagnostics": diagnostics}

    limit_n = max(1, int(limit or 1))

    headers = {"User-Agent": "Mozilla/5.0"}
    document_urls: List[str] = []
    seen_document_urls: set[str] = set()
    seen_pages: set[str] = set()
    pending_pages: List[str] = list(frontier[:2])

    async def _requests_get_text(fetch_url: str) -> str:
        response = await asyncio.to_thread(requests.get, fetch_url, timeout=25, headers=headers)
        response.raise_for_status()
        return str(response.text or "")

    async def _fetch_html(page_url: str) -> str:
        last_exc: Optional[Exception] = None
        fetch_urls = []
        iframe_url = _wayback_iframe_replay_url(page_url)
        fetch_urls.append(page_url)
        if iframe_url and iframe_url != page_url:
            fetch_urls.append(iframe_url)
        attempted_urls: set[str] = set(fetch_urls)
        for fetch_url in fetch_urls:
            for attempt in range(3):
                diagnostics["fetch_attempts"] = int(diagnostics.get("fetch_attempts", 0)) + 1
                try:
                    html = await _requests_get_text(fetch_url)
                    if html:
                        soup = BeautifulSoup(html, "html.parser")
                        title = ""
                        text = soup.get_text(" ", strip=True)
                        if soup.title is not None:
                            title = re.sub(r"\s+", " ", soup.title.get_text(" ", strip=True)).strip()
                        if _looks_like_wayback_shell_page(title=title, text=text) or _looks_like_new_hampshire_blocked_page(title=title, text=text):
                            diagnostics["shell_pages_rejected"] = int(diagnostics.get("shell_pages_rejected", 0)) + 1
                            continue
                    diagnostics["pages_fetched"] = int(diagnostics.get("pages_fetched", 0)) + 1
                    return html
                except Exception as exc:
                    last_exc = exc
                    if attempt < 2:
                        await asyncio.sleep(0.5 * (attempt + 1))
        capture_candidates = await asyncio.to_thread(_discover_wayback_capture_candidates, page_url, limit=4)
        diagnostics["capture_candidates_discovered"] = int(diagnostics.get("capture_candidates_discovered", 0)) + len(capture_candidates)
        for candidate_url in capture_candidates:
            if candidate_url in attempted_urls:
                continue
            attempted_urls.add(candidate_url)
            candidate_iframe = _wayback_iframe_replay_url(candidate_url)
            candidate_fetch_urls = [candidate_url]
            if candidate_iframe and candidate_iframe != candidate_url and candidate_iframe not in attempted_urls:
                candidate_fetch_urls.append(candidate_iframe)
                attempted_urls.add(candidate_iframe)
            for fetch_url in candidate_fetch_urls:
                diagnostics["fetch_attempts"] = int(diagnostics.get("fetch_attempts", 0)) + 1
                try:
                    html = await _requests_get_text(fetch_url)
                except Exception as exc:
                    last_exc = exc
                    continue
                if html:
                    soup = BeautifulSoup(html, "html.parser")
                    title = ""
                    text = soup.get_text(" ", strip=True)
                    if soup.title is not None:
                        title = re.sub(r"\s+", " ", soup.title.get_text(" ", strip=True)).strip()
                    if _looks_like_wayback_shell_page(title=title, text=text) or _looks_like_new_hampshire_blocked_page(title=title, text=text):
                        diagnostics["shell_pages_rejected"] = int(diagnostics.get("shell_pages_rejected", 0)) + 1
                        continue
                diagnostics["pages_fetched"] = int(diagnostics.get("pages_fetched", 0)) + 1
                return html
        for fetch_url in fetch_urls:
            diagnostics["fetch_attempts"] = int(diagnostics.get("fetch_attempts", 0)) + 1
            fetched = await _fetch_html_bypassing_challenge(fetch_url)
            if fetched is None:
                continue
            html = str(fetched.get("html") or "")
            text = str(fetched.get("text") or "")
            if not html and text:
                html = text
            if html:
                soup = BeautifulSoup(html, "html.parser")
                title = ""
                extracted_text = text or soup.get_text(" ", strip=True)
                if soup.title is not None:
                    title = re.sub(r"\s+", " ", soup.title.get_text(" ", strip=True)).strip()
                if _looks_like_wayback_shell_page(title=title, text=extracted_text) or _looks_like_new_hampshire_blocked_page(title=title, text=extracted_text):
                    diagnostics["shell_pages_rejected"] = int(diagnostics.get("shell_pages_rejected", 0)) + 1
                    continue
                diagnostics["pages_fetched"] = int(diagnostics.get("pages_fetched", 0)) + 1
                return html
        if last_exc is not None:
            diagnostics["fetch_failures"] = int(diagnostics.get("fetch_failures", 0)) + 1
            raise last_exc
        diagnostics["fetch_failures"] = int(diagnostics.get("fetch_failures", 0)) + 1
        return ""

    def _record_document_url(link_url: str) -> bool:
        link_url = _normalize_new_hampshire_archived_wayback_url(link_url)
        if not _is_new_hampshire_archived_rule_leaf_url(link_url):
            return False
        link_key = _url_key(link_url)
        if not link_key or link_key in seen_document_urls:
            return False
        seen_document_urls.add(link_key)
        document_urls.append(link_url)
        diagnostics["document_urls_found"] = len(document_urls)
        return len(document_urls) >= limit_n

    while pending_pages and len(document_urls) < limit_n:
        page_url = pending_pages.pop(0)
        page_key = _url_key(page_url)
        if not page_key or page_key in seen_pages:
            continue
        seen_pages.add(page_key)
        diagnostics["pages_attempted"] = int(diagnostics.get("pages_attempted", 0)) + 1
        try:
            html = await _fetch_html(page_url)
        except Exception:
            continue
        if not html:
            continue
        page_host = urlparse(str(page_url or "").strip()).netloc
        candidate_links = _candidate_links_from_html(
            html,
            base_host=page_host,
            page_url=page_url,
            limit=max(limit_n * 8, 48),
            allowed_hosts=allowed_hosts,
        )
        diagnostics["links_considered"] = int(diagnostics.get("links_considered", 0)) + len(candidate_links)
        for link_url in candidate_links:
            link_url = _normalize_new_hampshire_archived_wayback_url(link_url)
            if _record_document_url(link_url):
                return {"document_urls": document_urls, "diagnostics": diagnostics}
            if _looks_like_new_hampshire_archived_rule_inventory(text="", title="", url=link_url):
                link_page_key = _url_key(link_url)
                if link_page_key and link_page_key not in seen_pages and link_url not in pending_pages:
                    pending_pages.append(link_url)
                    diagnostics["inventory_pages_enqueued"] = int(diagnostics.get("inventory_pages_enqueued", 0)) + 1
    return {"document_urls": document_urls, "diagnostics": diagnostics}


async def _discover_new_hampshire_archived_rule_document_urls(
    *,
    seed_urls: List[str],
    allowed_hosts: Optional[set[str]] = None,
    limit: int = 8,
) -> List[str]:
    result = await _discover_new_hampshire_archived_rule_document_urls_with_diagnostics(
        seed_urls=seed_urls,
        allowed_hosts=allowed_hosts,
        limit=limit,
    )
    return list(result.get("document_urls") or [])


async def _scrape_new_hampshire_archived_rule_detail(url: str) -> Optional[Any]:
    archived_url = _normalize_new_hampshire_archived_wayback_url(url)
    if not _is_new_hampshire_archived_rule_leaf_url(archived_url):
        return None

    original_url = _wayback_replay_original_url(archived_url)
    replay_timestamp = _wayback_replay_timestamp(archived_url)
    fetch_candidates: List[str] = []
    fetch_candidates.append(archived_url)
    if original_url:
        fetch_candidates.append(original_url)
    iframe_url = _wayback_iframe_replay_url(archived_url)
    if iframe_url and iframe_url not in fetch_candidates and iframe_url != archived_url:
        fetch_candidates.append(iframe_url)

    if original_url and replay_timestamp:
        try:
            from ipfs_datasets_py.processors.web_archiving import wayback_machine_engine
        except Exception:
            wayback_machine_engine = None

        if wayback_machine_engine is not None:
            try:
                content_result = await wayback_machine_engine.get_wayback_content(
                    url=original_url,
                    timestamp=replay_timestamp,
                    closest=True,
                )
            except Exception:
                content_result = {"status": "error"}

            if isinstance(content_result, dict) and content_result.get("status") == "success":
                content = content_result.get("content", b"")
                if isinstance(content, bytes):
                    html = content.decode("utf-8", errors="replace")
                else:
                    html = str(content or "")
                if html.strip():
                    soup = BeautifulSoup(html, "html.parser")
                    title = ""
                    if soup.title is not None:
                        title = re.sub(r"\s+", " ", soup.title.get_text(" ", strip=True)).strip()
                    text = soup.get_text(" ", strip=True)
                    if text.strip() and not _looks_like_wayback_shell_page(title=title, text=text) and not _looks_like_new_hampshire_blocked_page(title=title, text=text):
                        return SimpleNamespace(
                            url=archived_url,
                            title=title,
                            text=text,
                            html=html,
                            links=[],
                            success=True,
                            method_used="new_hampshire_wayback_replay",
                            extraction_provenance={
                                "method": "new_hampshire_wayback_replay",
                                "source": "wayback_engine",
                                "fetch_url": str(content_result.get("wayback_url") or original_url),
                                "original_url": original_url or archived_url,
                                "capture_timestamp": str(content_result.get("capture_timestamp") or replay_timestamp),
                            },
                        )

    for fetch_url in fetch_candidates:
        fetched = await _fetch_html_bypassing_challenge(fetch_url)
        if fetched is None:
            continue
        text = str(fetched.get("text") or "").strip()
        html = str(fetched.get("html") or "")
        if not text and not html:
            continue
        title = ""
        if html:
            soup = BeautifulSoup(html, "html.parser")
            if soup.title is not None:
                title = re.sub(r"\s+", " ", soup.title.get_text(" ", strip=True)).strip()
        if _looks_like_wayback_shell_page(title=title, text=text) or _looks_like_new_hampshire_blocked_page(title=title, text=text):
            continue
        return SimpleNamespace(
            url=archived_url,
            title=title,
            text=text,
            html=html,
            links=[],
            success=True,
            method_used="new_hampshire_wayback_replay",
            extraction_provenance={
                "method": "new_hampshire_wayback_replay",
                "source": str(fetched.get("source") or ""),
                "fetch_url": fetch_url,
                "original_url": original_url or archived_url,
                "capture_timestamp": replay_timestamp,
            },
        )

    return None


async def _scrape_alabama_rule_detail_via_api(url: str) -> Optional[Any]:
    rule_number = _alabama_public_code_number_from_url(url)
    if not _AL_RULE_NUMBER_RE.fullmatch(rule_number):
        return None

    def _run() -> Optional[Any]:
        data = _post_alabama_persisted_query(
            operation_name="publicCode",
            sha_hash=_AL_PUBLIC_CODE_HASH,
            variables={"number": rule_number},
        )
        document = (data or {}).get("document") or {}
        if not isinstance(document, dict) or str(document.get("__typename") or "") != "Rule":
            return None

        id_text = str(document.get("idText") or rule_number).strip()
        catchline = str(document.get("title") or "").strip()
        title = f"{id_text} {catchline}".strip()

        html_parts: List[str] = []
        description_html = str(document.get("description") or "").strip()
        if description_html:
            html_parts.append(description_html)
        for label, key in (
            ("Authority", "authority"),
            ("History", "history"),
            ("Penalty", "penalty"),
            ("Editor's Note", "editorsNote"),
        ):
            value = str(document.get(key) or "").strip()
            if value:
                html_parts.append(f"<p><strong>{label}:</strong> {value}</p>")
        html = "".join(html_parts).strip()
        text = _extract_text_from_downloaded_html_document(html)
        if not text:
            fallback_parts = [str(document.get("description") or "").strip()]
            for key in ("authority", "history", "penalty", "editorsNote"):
                fallback_parts.append(str(document.get(key) or "").strip())
            text = "\n\n".join(part for part in fallback_parts if part).strip()
        if not text:
            return None

        return SimpleNamespace(
            url=url,
            title=title,
            text=text,
            html=html,
            links=[],
            success=True,
            method_used="alabama_public_code_api",
            extraction_provenance={"method": "alabama_public_code_api"},
        )

    return await asyncio.to_thread(_run)


async def _scrape_oklahoma_rule_detail_via_api(url: str) -> Optional[Any]:
    title_num, section_num = _oklahoma_rule_identifiers_from_url(url)
    if not title_num:
        return None

    def _run() -> Optional[Any]:
        segments_payload = _get_oklahoma_title_segments_payload(title_num)
        if not segments_payload:
            return None

        title_label = next(
            (
                str(item.get("description") or "").strip()
                for item in segments_payload or []
                if isinstance(item, dict) and str(item.get("name") or "").strip().lower() == "title"
            ),
            "",
        )

        if section_num:
            segment = next(
                (
                    item
                    for item in segments_payload or []
                    if isinstance(item, dict) and str(item.get("sectionNum") or "").strip() == section_num
                ),
                None,
            )
            if not isinstance(segment, dict):
                return None

            description = str(segment.get("description") or "").strip()
            segment_html = str(segment.get("text") or "").strip()
            text = _extract_text_from_downloaded_html_document(segment_html)
            if not text:
                text = BeautifulSoup(segment_html, "html.parser").get_text("\n", strip=True)
            if not text:
                return None

            title = " ".join(part for part in (section_num, description) if part).strip()
            html = segment_html
        else:
            text_parts: List[str] = []
            html_parts: List[str] = []
            for item in segments_payload or []:
                if not isinstance(item, dict):
                    continue
                if str(item.get("name") or "").strip().lower() != "section":
                    continue
                item_section_num = str(item.get("sectionNum") or "").strip()
                if not _OK_RULE_SECTION_NUM_RE.fullmatch(item_section_num):
                    continue
                item_description = str(item.get("description") or "").strip()
                item_html = str(item.get("text") or "").strip()
                item_text = _extract_text_from_downloaded_html_document(item_html)
                if not item_text:
                    item_text = BeautifulSoup(item_html, "html.parser").get_text("\n", strip=True)
                if not item_text:
                    continue
                item_title = " ".join(part for part in (item_section_num, item_description) if part).strip()
                if item_title:
                    text_parts.append(item_title)
                    html_parts.append(f"<h2>{__import__('html').escape(item_title)}</h2>")
                text_parts.append(item_text)
                if item_html:
                    html_parts.append(item_html)

            text = "\n\n".join(part for part in text_parts if part).strip()
            html = "".join(html_parts).strip()
            if not text:
                return None
            title = " ".join(part for part in (f"Title {title_num}", title_label) if part).strip()

        return SimpleNamespace(
            url=url,
            title=title,
            text=text,
            html=html,
            links=[],
            success=True,
            method_used="oklahoma_rules_api",
            extraction_provenance={"method": "oklahoma_rules_api"},
        )

    return await asyncio.to_thread(_run)


def _candidate_tennessee_rule_urls_from_html(*, html: str, page_url: str = "", limit: int = 12) -> List[str]:
    body = str(html or "")
    if not body:
        return []

    page_host = urlparse(str(page_url or "").strip()).netloc.lower()
    if page_host not in {"sharetngov.tnsosfiles.com", "publications.tnsosfiles.com", "sos.tn.gov", "www.tn.gov", "tn.gov"}:
        if "sharetngov.tnsosfiles.com/sos/rules" not in body.lower():
            return []

    ranked: List[tuple[int, str, str]] = []
    seen: set[str] = set()

    def _family_key(candidate_url: str) -> str:
        parsed = urlparse(candidate_url)
        path_parts = [part for part in (parsed.path or "").split("/") if part]
        if len(path_parts) >= 5 and path_parts[:2] == ["sos", "rules"]:
            return "/".join(path_parts[:4])
        if len(path_parts) >= 3 and path_parts[:2] == ["sos", "rules"]:
            return "/".join(path_parts[:3])
        return parsed.path or candidate_url

    def _maybe_add(candidate_url: str) -> None:
        normalized_url = str(candidate_url or "").strip()
        if not normalized_url:
            return
        if not normalized_url.startswith(("http://", "https://")) and page_url:
            normalized_url = urljoin(page_url, normalized_url)
        if not normalized_url.startswith(("http://", "https://")):
            return

        parsed = urlparse(normalized_url)
        host = parsed.netloc.lower()
        path = parsed.path or ""
        if host != "sharetngov.tnsosfiles.com":
            return
        if not (
            re.search(r"^/sos/rules/\d{4}/\d{4}\.htm$", path, re.IGNORECASE)
            or re.search(r"^/sos/rules/\d{4}/[\d-]+/[\d-]+\.htm$", path, re.IGNORECASE)
            or re.search(r"^/sos/rules/\d{4}/[\w.-]+\.pdf$", path, re.IGNORECASE)
            or re.search(r"^/sos/rules/\d{4}/[\d-]+/[\w.-]+\.pdf$", path, re.IGNORECASE)
        ):
            return

        key = _url_key(normalized_url)
        if not key or key in seen:
            return
        seen.add(key)

        score = _score_candidate_url(normalized_url)
        if _is_pdf_candidate_url(normalized_url):
            score += 4
        elif re.search(r"^/sos/rules/\d{4}/[\d-]+/[\d-]+\.htm$", path, re.IGNORECASE):
            score += 1
        if score <= 0:
            return
        ranked.append((score, _family_key(normalized_url), normalized_url))

    for href in re.findall(r'<a\b[^>]*href=["\']([^"\']+)["\']', body, re.IGNORECASE):
        _maybe_add(unescape(str(href or "").strip()))

    ranked.sort(key=lambda item: item[0], reverse=True)

    per_family_ranked: Dict[str, List[tuple[int, str]]] = {}
    for score, family_key, candidate_url in ranked:
        per_family_ranked.setdefault(family_key, []).append((score, candidate_url))

    ordered_family_keys = sorted(
        per_family_ranked,
        key=lambda family_key: per_family_ranked[family_key][0][0],
        reverse=True,
    )

    limit_n = max(1, int(limit))
    discovered_urls: List[str] = []
    family_positions = {family_key: 0 for family_key in ordered_family_keys}
    while len(discovered_urls) < limit_n:
        made_progress = False
        for family_key in ordered_family_keys:
            family_candidates = per_family_ranked[family_key]
            position = family_positions[family_key]
            if position >= len(family_candidates):
                continue
            discovered_urls.append(family_candidates[position][1])
            family_positions[family_key] = position + 1
            made_progress = True
            if len(discovered_urls) >= limit_n:
                return discovered_urls
        if not made_progress:
            break

    return discovered_urls


def _candidate_hawaii_rule_urls_from_html(*, html: str, page_url: str = "", limit: int = 12) -> List[str]:
    body = str(html or "")
    if not body:
        return []

    page_url_value = str(page_url or "").strip()
    page_host = urlparse(page_url_value).netloc.lower()
    if page_host not in {"cca.hawaii.gov", "ag.hawaii.gov", "labor.hawaii.gov", "ltgov.hawaii.gov"}:
        return []

    ranked: List[tuple[int, str]] = []
    seen: set[str] = set()

    def _maybe_add(candidate_url: str, label: str = "") -> None:
        normalized_url = str(candidate_url or "").strip()
        if not normalized_url:
            return
        if not normalized_url.startswith(("http://", "https://")) and page_url_value:
            normalized_url = urljoin(page_url_value, normalized_url)
        if not normalized_url.startswith(("http://", "https://")):
            return

        parsed = urlparse(normalized_url)
        host = parsed.netloc.lower()
        path = parsed.path or ""
        file_name = path.rsplit("/", 1)[-1].lower()
        if not _is_pdf_candidate_url(normalized_url):
            return

        label_value = " ".join(str(label or "").split())
        signal = " ".join([normalized_url, label_value]).lower()
        if host == "files.hawaii.gov":
            if not re.search(r"^/dcca/[^/]+/har/[\w.-]+\.pdf$", path, re.IGNORECASE):
                return
        elif host in {"ag.hawaii.gov", "labor.hawaii.gov", "cca.hawaii.gov"}:
            if not any(token in signal for token in ("har", "chapter", "administrative")):
                return
        else:
            return

        key = _url_key(normalized_url)
        if not key or key in seen:
            return
        seen.add(key)

        score = _score_candidate_url(normalized_url) + 4
        if "chapter" in signal:
            score += 2
        if host == "files.hawaii.gov":
            score += 2
        ranked.append((score, normalized_url))

    soup = BeautifulSoup(body, "html.parser")
    for anchor in soup.find_all("a", href=True):
        _maybe_add(str(anchor.get("href") or ""), str(anchor.get_text(" ", strip=True) or ""))

    ranked.sort(key=lambda item: item[0], reverse=True)
    return [value for _, value in ranked[: max(1, int(limit))]]


async def _discover_hawaii_rule_document_urls(*, seed_urls: List[str], limit: int = 8) -> List[str]:
    relevant_seed_urls = [
        str(url or "").strip()
        for url in list(seed_urls or [])
        if urlparse(str(url or "").strip()).netloc.lower()
        in {"cca.hawaii.gov", "ag.hawaii.gov", "labor.hawaii.gov", "ltgov.hawaii.gov"}
    ]
    if not relevant_seed_urls:
        return []

    limit_n = max(1, int(limit))

    def _run() -> List[str]:
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        session = requests.Session()
        discovered_urls: List[str] = []
        seen_documents: set[str] = set()

        preferred_seed_urls: List[str] = []
        for preferred_url in (
            "https://cca.hawaii.gov/hawaii-administrative-rules/",
            "https://labor.hawaii.gov/administrative-rules/",
            "https://ag.hawaii.gov/publications/administrative-rules/",
            "https://ltgov.hawaii.gov/the-office/administrative-rules/",
        ):
            if preferred_url in relevant_seed_urls and preferred_url not in preferred_seed_urls:
                preferred_seed_urls.append(preferred_url)
        for seed_url in relevant_seed_urls:
            if seed_url not in preferred_seed_urls:
                preferred_seed_urls.append(seed_url)

        for seed_url in preferred_seed_urls[:4]:
            try:
                response = session.get(seed_url, timeout=25, headers=headers)
                response.raise_for_status()
            except Exception:
                continue

            for candidate_url in _candidate_hawaii_rule_urls_from_html(
                html=str(getattr(response, "text", "") or ""),
                page_url=seed_url,
                limit=max(limit_n * 4, 24),
            ):
                key = _url_key(candidate_url)
                if not key or key in seen_documents:
                    continue
                seen_documents.add(key)
                discovered_urls.append(candidate_url)
                if len(discovered_urls) >= limit_n:
                    return discovered_urls

        return discovered_urls

    return await asyncio.to_thread(_run)


def _candidate_louisiana_rule_urls_from_html(*, html: str, page_url: str = "", limit: int = 12) -> List[str]:
    body = str(html or "")
    if not body:
        return []

    page_url_value = str(page_url or "").strip()
    page_host = urlparse(page_url_value).netloc.lower()
    if page_host not in {"www.sos.la.gov", "sos.la.gov"}:
        return []

    ranked: List[tuple[int, str]] = []
    seen: set[str] = set()

    def _maybe_add(candidate_url: str, label: str = "") -> None:
        normalized_url = str(candidate_url or "").strip()
        if not normalized_url:
            return
        if not normalized_url.startswith(("http://", "https://")) and page_url_value:
            normalized_url = urljoin(page_url_value, normalized_url)
        if not normalized_url.startswith(("http://", "https://")):
            return

        parsed = urlparse(normalized_url)
        host = parsed.netloc.lower()
        path = parsed.path or ""
        if host not in {"www.sos.la.gov", "sos.la.gov"}:
            return
        if "/publisheddocuments/" not in path.lower() or not path.lower().endswith(".pdf"):
            return

        file_name = unquote(path.rsplit("/", 1)[-1]).lower()
        signal = " ".join(part for part in (file_name, str(label or "").lower()) if part)
        if not any(token in signal for token in ("title", "chapter", "rule", "administrative", "corporations", "ucc", "uniform commercial code")):
            return
        if any(
            token in signal
            for token in (
                "notice",
                "agenda",
                "hearing",
                "annualreport",
                "annual report",
                "legislative",
                "oversight",
                "summaryreport",
                "summary report",
                "initialreport",
                "secondreport",
                "potpourri",
                "sexual harassment",
                "policy",
                "emergency modification",
            )
        ):
            return

        key = _url_key(normalized_url)
        if not key or key in seen:
            return
        seen.add(key)
        score = _score_candidate_url(normalized_url)
        if any(
            token in signal
            for token in (
                "partiichapter1registrarsofvoters",
                "partiichapter3voterregistrationatdriverslicensefacilities",
                "partiichapter5voterregistrationatoptionalvoterregistrationagencies",
                "registrars of voters",
                "voter registration",
            )
        ):
            score += 5
        if any(
            token in signal
            for token in (
                "chapter3opportunitytocuredeficiencies",
                "chapter5electionnighttransmissionofresults",
                "chapter8votingtechnologyfund",
                "chapter9recognitionofpoliticalparties",
                "chapter11emergencyelectiondaypaperballotprocedures",
                "opportunity to cure deficiencies",
                "election night transmission of results",
                "voting technology fund",
                "recognition of political parties",
                "emergency election day paper ballot procedures",
            )
        ):
            score -= 4
        if score <= 0:
            return
        ranked.append((score, normalized_url))

    soup = BeautifulSoup(body, "html.parser")
    for anchor in soup.find_all("a", href=True):
        _maybe_add(str(anchor.get("href") or ""), str(anchor.get_text(" ", strip=True) or ""))

    ranked.sort(key=lambda item: item[0], reverse=True)
    return [value for _, value in ranked[: max(1, int(limit))]]


async def _discover_louisiana_rule_document_urls(*, seed_urls: List[str], limit: int = 8) -> List[str]:
    relevant_seed_urls = [
        str(url or "").strip()
        for url in list(seed_urls or [])
        if urlparse(str(url or "").strip()).netloc.lower() in {"www.sos.la.gov", "sos.la.gov"}
    ]
    if not relevant_seed_urls:
        return []

    limit_n = max(1, int(limit))

    def _run() -> List[str]:
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        session = requests.Session()
        seen_documents: set[str] = set()
        per_seed_candidate_urls: List[List[str]] = []

        preferred_seed_urls: List[str] = []
        for preferred_url in (
            "https://www.sos.la.gov/BusinessServices/Pages/ReadAdministrativeRules.aspx",
            "https://www.sos.la.gov/ElectionsAndVoting/ReviewAdministrationAndHistory/ReadAdministrativeRules/Pages/default.aspx",
            "https://www.sos.la.gov/OurOffice/FindAdministrativeRules/Pages/default.aspx",
        ):
            if preferred_url in relevant_seed_urls and preferred_url not in preferred_seed_urls:
                preferred_seed_urls.append(preferred_url)
        for seed_url in relevant_seed_urls:
            if seed_url not in preferred_seed_urls:
                preferred_seed_urls.append(seed_url)

        for seed_url in preferred_seed_urls[:4]:
            try:
                response = session.get(seed_url, timeout=25, headers=headers)
                response.raise_for_status()
            except Exception:
                continue

            candidate_urls = _candidate_louisiana_rule_urls_from_html(
                html=str(getattr(response, "text", "") or ""),
                page_url=seed_url,
                limit=max(limit_n * 4, 24),
            )
            if candidate_urls:
                per_seed_candidate_urls.append(candidate_urls)

        if not per_seed_candidate_urls:
            return []

        discovered_urls: List[str] = []
        seed_positions = [0 for _ in per_seed_candidate_urls]
        while len(discovered_urls) < limit_n:
            made_progress = False
            for seed_index, candidate_urls in enumerate(per_seed_candidate_urls):
                while seed_positions[seed_index] < len(candidate_urls):
                    candidate_url = candidate_urls[seed_positions[seed_index]]
                    seed_positions[seed_index] += 1
                    key = _url_key(candidate_url)
                    if not key or key in seen_documents:
                        continue
                    seen_documents.add(key)
                    discovered_urls.append(candidate_url)
                    made_progress = True
                    break
                if len(discovered_urls) >= limit_n:
                    return discovered_urls
            if not made_progress:
                break

        return discovered_urls

    return await asyncio.to_thread(_run)


async def _discover_rhode_island_rule_document_urls(*, seed_urls: List[str], limit: int = 8) -> List[str]:
    relevant_seed_urls = [
        str(url or "").strip()
        for url in list(seed_urls or [])
        if urlparse(str(url or "").strip()).netloc.lower() in {"www.sos.ri.gov", "sos.ri.gov"}
        and "/rules-and-regulations" in (urlparse(str(url or "").strip()).path or "").lower()
    ]

    preferred_seed_urls: List[str] = []
    for preferred_url in (
        "https://www.sos.ri.gov/divisions/open-government-center/rules-and-regulations/building-and-fire-codes",
        "https://www.sos.ri.gov/divisions/open-government-center/rules-and-regulations",
    ):
        if preferred_url not in preferred_seed_urls:
            preferred_seed_urls.append(preferred_url)
    for seed_url in relevant_seed_urls:
        if seed_url not in preferred_seed_urls:
            preferred_seed_urls.append(seed_url)

    if not preferred_seed_urls:
        return []

    limit_n = max(1, int(limit))

    def _run() -> List[str]:
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        discovered_urls: List[str] = []
        seen: set[str] = set()

        for seed_url in preferred_seed_urls[:4]:
            try:
                response = requests.get(seed_url, timeout=25, headers=headers)
                response.raise_for_status()
            except Exception:
                continue

            soup = BeautifulSoup(str(getattr(response, "text", "") or ""), "html.parser")
            for anchor in soup.find_all("a", href=True):
                candidate_url = urldefrag(urljoin(seed_url, str(anchor.get("href") or "").strip())).url
                if not _is_direct_detail_candidate_url(candidate_url):
                    continue
                key = _url_key(candidate_url)
                if not key or key in seen:
                    continue
                seen.add(key)
                discovered_urls.append(candidate_url)
                if len(discovered_urls) >= limit_n:
                    return discovered_urls

        return discovered_urls

    return await asyncio.to_thread(_run)


async def _discover_iowa_rule_document_urls(*, seed_urls: List[str], limit: int = 8) -> List[str]:
    relevant_seed_urls = [
        str(url or "").strip()
        for url in list(seed_urls or [])
        if urlparse(str(url or "").strip()).netloc.lower() in {"www.legis.iowa.gov", "legis.iowa.gov"}
    ]
    if not relevant_seed_urls:
        return []

    limit_n = max(1, int(limit))

    def _run() -> List[str]:
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        session = requests.Session()
        discovered_urls: List[str] = []
        seen_documents: set[str] = set()

        preferred_seed_urls: List[str] = []
        for preferred_url in (
            "https://www.legis.iowa.gov/law/administrativeRules/agencies",
            "https://www.legis.iowa.gov/law/administrativeRules",
        ):
            if preferred_url in relevant_seed_urls and preferred_url not in preferred_seed_urls:
                preferred_seed_urls.append(preferred_url)
        for seed_url in relevant_seed_urls:
            if seed_url not in preferred_seed_urls:
                preferred_seed_urls.append(seed_url)

        for seed_url in preferred_seed_urls[:3]:
            try:
                response = session.get(seed_url, timeout=25, headers=headers)
                response.raise_for_status()
            except Exception:
                continue

            soup = BeautifulSoup(str(getattr(response, "text", "") or ""), "html.parser")
            ranked: List[tuple[int, str]] = []

            for anchor in soup.find_all("a", href=True):
                href = str(anchor.get("href") or "").strip()
                if not href:
                    continue
                candidate_url = urljoin(seed_url, href)
                parsed = urlparse(candidate_url)
                if parsed.netloc.lower() not in {"www.legis.iowa.gov", "legis.iowa.gov"}:
                    continue

                path_lower = (parsed.path or "").lower()
                if not re.fullmatch(r"/docs/iac/agency/[0-9]{2}-[0-9]{2}-[0-9]{4}\.[0-9]+\.pdf", path_lower):
                    continue

                key = _url_key(candidate_url)
                if not key or key in seen_documents:
                    continue

                score = _score_candidate_url(candidate_url)
                ranked.append((score if score > 0 else 1, candidate_url))

            ranked.sort(key=lambda item: item[0], reverse=True)
            for _, candidate_url in ranked:
                key = _url_key(candidate_url)
                if not key or key in seen_documents:
                    continue
                seen_documents.add(key)
                discovered_urls.append(candidate_url)
                if len(discovered_urls) >= limit_n:
                    return discovered_urls

        return discovered_urls

    return await asyncio.to_thread(_run)


async def _discover_tennessee_rule_document_urls(*, seed_urls: List[str], limit: int = 8) -> List[str]:
    relevant_seed_urls = [
        str(url or "").strip()
        for url in list(seed_urls or [])
        if urlparse(str(url or "").strip()).netloc.lower()
        in {"sharetngov.tnsosfiles.com", "publications.tnsosfiles.com", "sos.tn.gov", "www.tn.gov", "tn.gov"}
    ]
    if not relevant_seed_urls:
        return []

    limit_n = max(1, int(limit))

    def _run() -> List[str]:
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        session = requests.Session()
        discovered_urls: List[str] = []
        seen_documents: set[str] = set()
        seen_pages: set[str] = set()

        frontier: List[str] = [
            "https://sharetngov.tnsosfiles.com/sos/rules/index.htm",
            "https://sharetngov.tnsosfiles.com/sos/rules/rules2.htm",
        ]
        deferred_frontier: List[str] = [
            "https://sharetngov.tnsosfiles.com/sos/rules/tenncare.htm",
        ]
        for seed_url in relevant_seed_urls:
            if seed_url not in frontier and seed_url not in deferred_frontier:
                frontier.append(seed_url)

        def _record(candidate_url: str) -> bool:
            if not _is_pdf_candidate_url(candidate_url):
                return False
            key = _url_key(candidate_url)
            if not key or key in seen_documents:
                return False
            seen_documents.add(key)
            discovered_urls.append(candidate_url)
            return len(discovered_urls) >= limit_n

        for _depth in range(3):
            next_frontier: List[str] = []
            for page_url in frontier[:4]:
                page_key = _url_key(page_url)
                if not page_key or page_key in seen_pages:
                    continue
                seen_pages.add(page_key)

                try:
                    response = session.get(page_url, timeout=15, headers=headers)
                    response.raise_for_status()
                except Exception:
                    continue

                for candidate_url in _candidate_tennessee_rule_urls_from_html(
                    html=response.text,
                    page_url=page_url,
                    limit=max(limit_n * 6, 24),
                ):
                    if _record(candidate_url):
                        return discovered_urls
                    if _is_pdf_candidate_url(candidate_url):
                        continue
                    candidate_key = _url_key(candidate_url)
                    if not candidate_key or candidate_key in seen_pages:
                        continue
                    if candidate_url not in next_frontier:
                        next_frontier.append(candidate_url)

            frontier = next_frontier
            if not frontier and deferred_frontier:
                frontier = deferred_frontier
                deferred_frontier = []
            if not frontier:
                break

        return discovered_urls

    return await asyncio.to_thread(_run)


async def _scrape_south_dakota_rule_detail_via_api(url: str) -> Optional[Any]:
    rule_reference = _south_dakota_rule_reference_from_url(url)
    if not rule_reference:
        return None

    def _run() -> Optional[Any]:
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://sdlegislature.gov/Rules/Administrative",
        }
        try:
            response = requests.get(
                f"https://sdlegislature.gov/api/Rules/{rule_reference}",
                timeout=25,
                headers=headers,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception:
            return None

        if not isinstance(payload, dict):
            return None

        html = str(payload.get("Html") or "").strip()
        if not html:
            try:
                html_response = requests.get(
                    f"https://sdlegislature.gov/api/Rules/Rule/{rule_reference}.html",
                    params={"all": "true"},
                    timeout=25,
                    headers={
                        "User-Agent": "Mozilla/5.0",
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                        "Referer": "https://sdlegislature.gov/Rules/Administrative",
                    },
                )
                html_response.raise_for_status()
                html = str(html_response.text or "").strip()
            except Exception:
                html = ""

        text = _extract_text_from_downloaded_html_document(html)
        if not text:
            content_value = payload.get("Content")
            if isinstance(content_value, str):
                text = str(content_value).strip()
        if not text:
            return None

        rule_number = str(payload.get("RuleNumber") or rule_reference).strip()
        catchline = str(payload.get("Catchline") or "").strip()
        title = f"{rule_number} {catchline}".strip()

        return SimpleNamespace(
            url=url,
            title=title,
            text=text,
            html=html,
            links=[],
            success=True,
            method_used="south_dakota_rules_api",
            extraction_provenance={"method": "south_dakota_rules_api"},
        )

    return await asyncio.to_thread(_run)


def _iter_utah_public_search_rules(payload: Any) -> List[Dict[str, Any]]:
    rules: List[Dict[str, Any]] = []
    for agency in payload or []:
        if not isinstance(agency, dict):
            continue
        for program in agency.get("programs") or []:
            if not isinstance(program, dict):
                continue
            for rule in program.get("rules") or []:
                if isinstance(rule, dict):
                    rules.append(rule)
    return rules


async def _scrape_utah_rule_detail_via_public_download(url: str) -> Optional[Any]:
    parsed = urlparse(str(url or "").strip())
    if parsed.netloc.lower() != "adminrules.utah.gov":
        return None
    if not _UT_RULE_DETAIL_PATH_RE.search(parsed.path or ""):
        return None

    reference_number = _utah_rule_reference_from_url(url)
    if not reference_number:
        return None
    rule_type = _utah_rule_type_from_url(url)

    headers = {
        "Accept": "application/json,text/plain,*/*",
        "Referer": str(url or "").strip(),
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/123.0 Safari/537.36"
        ),
    }

    async def _requests_get_response(fetch_url: str, *, timeout: float, request_headers: Dict[str, str]) -> Any:
        response = await asyncio.to_thread(
            requests.get,
            fetch_url,
            timeout=timeout,
            headers=request_headers,
        )
        response.raise_for_status()
        return response

    decoded_rule_path = unquote(parsed.path or "")
    matched_rule = _get_cached_utah_rule_detail_metadata(url)
    if matched_rule is None:
        search_url = (
            "https://adminrules.utah.gov/api/public/searchRuleDataTotal/"
            f"{quote(reference_number, safe='')}/{quote(rule_type, safe='')}"
        )

        try:
            search_response = await _requests_get_response(search_url, timeout=35, request_headers=headers)
            payload = search_response.json()
        except Exception:
            return None

        for rule in _iter_utah_public_search_rules(payload):
            rule_reference = str(rule.get("referenceNumber") or "").strip().upper()
            link_to_rule = str(rule.get("linkToRule") or "").strip()
            if rule_reference == reference_number:
                matched_rule = rule
                break
            if link_to_rule and decoded_rule_path.endswith(link_to_rule):
                matched_rule = rule
                break
        if matched_rule is None:
            return None
        _cache_utah_rule_detail_metadata(url, matched_rule)

    title = str(matched_rule.get("name") or reference_number).strip()
    if title and not title.startswith(reference_number):
        title = f"{reference_number}. {title}"

    html_download = str(matched_rule.get("htmlDownload") or "").strip()
    html_download_name = str(matched_rule.get("htmlDownloadName") or "").strip()
    if html_download and html_download_name:
        html_url = (
            "https://adminrules.utah.gov/api/public/getfile/"
            f"{html_download}/{quote(html_download_name, safe='')}"
        )
        try:
            html_response = await _requests_get_response(
                html_url,
                timeout=35,
                request_headers={**headers, "Accept": "*/*"},
            )
            if "text/html" in str(html_response.headers.get("content-type") or "").lower():
                extracted_text = _extract_text_from_downloaded_html_document(html_response.text)
                if extracted_text:
                    return SimpleNamespace(
                        url=url,
                        title=title,
                        text=extracted_text,
                        html=html_response.text,
                        links=[],
                        success=True,
                        method_used="utah_public_getfile_html",
                        extraction_provenance={"method": "utah_public_getfile_html"},
                    )
        except Exception:
            pass

    pdf_download = str(matched_rule.get("pdfDownload") or "").strip()
    pdf_download_name = str(matched_rule.get("pdfDownloadName") or "").strip()
    if pdf_download and pdf_download_name:
        pdf_url = (
            "https://adminrules.utah.gov/api/public/getfile/"
            f"{pdf_download}/{quote(pdf_download_name, safe='')}"
        )
        try:
            pdf_response = await _requests_get_response(
                pdf_url,
                timeout=35,
                request_headers={**headers, "Accept": "application/pdf,*/*"},
            )
            extracted_text = await _extract_text_from_pdf_bytes_with_processor(pdf_response.content or b"", source_url=pdf_url)
            extracted_text = str(extracted_text or "").strip()
            if extracted_text:
                return SimpleNamespace(
                    url=url,
                    title=title,
                    text=extracted_text,
                    html="",
                    links=[],
                    success=True,
                    method_used="utah_public_getfile_pdf",
                    extraction_provenance={"method": "utah_public_getfile_pdf"},
                )
        except Exception:
            pass

    return None


def _pdf_request_headers(url: str) -> Dict[str, str]:
    parsed = urlparse(str(url or "").strip())
    referer = f"{parsed.scheme}://{parsed.netloc}/" if parsed.scheme and parsed.netloc else ""
    if parsed.netloc.lower() == "apps.azsos.gov":
        referer = "https://apps.azsos.gov/public_services/CodeTOC.htm"
    user_agent = str(os.getenv("IPFS_DATASETS_PY_DOC_REQUEST_USER_AGENT", "") or "").strip() or (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/123.0 Safari/537.36"
    )
    headers = {
        "User-Agent": user_agent,
        "Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": referer,
    }
    cookie_header = str(os.getenv("IPFS_DATASETS_PY_DOC_REQUEST_COOKIE", "") or "").strip()
    if cookie_header:
        headers["Cookie"] = cookie_header
    return headers


def _looks_like_browser_challenge(*, status_code: int, content_type: str, head: str) -> bool:
    if int(status_code) < 400 and "html" not in str(content_type or "").lower():
        return False
    return bool(_BROWSER_CHALLENGE_HTML_RE.search(str(head or "")))


def _use_persistent_playwright_profile() -> bool:
    value = str(os.getenv("IPFS_DATASETS_PY_PLAYWRIGHT_USE_PERSISTENT_PROFILE", "1") or "").strip().lower()
    return value not in {"0", "false", "no", "off"}


def _playwright_headless_enabled() -> bool:
    value = str(os.getenv("IPFS_DATASETS_PY_PLAYWRIGHT_HEADLESS", "1") or "").strip().lower()
    return value not in {"0", "false", "no", "off"}


def _playwright_persistent_profile_dir() -> Path:
    configured = str(os.getenv("IPFS_DATASETS_PY_PLAYWRIGHT_PERSISTENT_PROFILE_DIR", "") or "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".cache" / "ipfs_datasets_py" / "playwright" / "state_admin_rules"


def _playwright_storage_state_path() -> Optional[Path]:
    configured = str(os.getenv("IPFS_DATASETS_PY_PLAYWRIGHT_STORAGE_STATE", "") or "").strip()
    if not configured:
        return None
    return Path(configured).expanduser()


def _playwright_cookie_header() -> str:
    explicit = str(os.getenv("IPFS_DATASETS_PY_PLAYWRIGHT_COOKIE_HEADER", "") or "").strip()
    if explicit:
        return explicit
    return str(os.getenv("IPFS_DATASETS_PY_DOC_REQUEST_COOKIE", "") or "").strip()


def _playwright_cookies_from_header(url: str, cookie_header: str) -> List[Dict[str, Any]]:
    parsed = urlparse(str(url or "").strip())
    if not parsed.netloc:
        return []
    cookies: List[Dict[str, Any]] = []
    for raw_part in str(cookie_header or "").split(";"):
        part = raw_part.strip()
        if not part or "=" not in part:
            continue
        name, value = part.split("=", 1)
        name = name.strip()
        if not name:
            continue
        cookies.append(
            {
                "name": name,
                "value": value.strip(),
                "domain": parsed.netloc,
                "path": "/",
                "secure": parsed.scheme == "https",
                "httpOnly": False,
            }
        )
    return cookies


async def _apply_playwright_session_state(context: Any, page: Any, url: str) -> None:
    cookies: List[Dict[str, Any]] = []

    storage_state_path = _playwright_storage_state_path()
    if storage_state_path and storage_state_path.exists():
        try:
            storage_state = json.loads(storage_state_path.read_text(encoding="utf-8"))
        except Exception:
            storage_state = None
        if isinstance(storage_state, dict):
            storage_cookies = storage_state.get("cookies") or []
            if isinstance(storage_cookies, list):
                cookies.extend(cookie for cookie in storage_cookies if isinstance(cookie, dict))

    cookie_header = _playwright_cookie_header()
    if cookie_header:
        cookies.extend(_playwright_cookies_from_header(url, cookie_header))

    if cookies:
        try:
            await context.add_cookies(cookies)
        except Exception:
            pass

    if storage_state_path and storage_state_path.exists():
        try:
            storage_state = json.loads(storage_state_path.read_text(encoding="utf-8"))
        except Exception:
            storage_state = None
        origins = storage_state.get("origins") if isinstance(storage_state, dict) else None
        if isinstance(origins, list):
            for origin_entry in origins:
                if not isinstance(origin_entry, dict):
                    continue
                origin = str(origin_entry.get("origin") or "").strip()
                local_storage = origin_entry.get("localStorage") or []
                if not origin or not isinstance(local_storage, list):
                    continue
                try:
                    await page.goto(origin, wait_until="domcontentloaded", timeout=15000)
                    await page.evaluate(
                        """
                        (entries) => {
                          for (const entry of entries) {
                            if (!entry || typeof entry.name !== 'string') {
                              continue;
                            }
                            localStorage.setItem(entry.name, String(entry.value ?? ''));
                          }
                        }
                        """,
                        local_storage,
                    )
                except Exception:
                    continue


def _download_document_bytes_via_cloudscraper(url: str) -> Optional[Dict[str, Any]]:
    """Try to fetch a document URL using cloudscraper, then cfscrape, bypassing CF challenges."""
    headers = _pdf_request_headers(url)

    def _try_cloudscraper() -> Optional[Dict[str, Any]]:
        try:
            import cloudscraper as _cs
        except Exception:
            return None
        try:
            s = _cs.create_scraper(browser={"browser": "chrome", "platform": "linux", "desktop": True})
            resp = s.get(url, timeout=35, headers=headers)
        except Exception:
            return None
        sc = int(getattr(resp, "status_code", 599) or 599)
        ct = str(getattr(resp, "headers", {}).get("content-type") or "").lower()
        body = getattr(resp, "content", b"") or b""
        h = body[:1024].decode("latin1", errors="ignore")
        if sc >= 400 or _looks_like_browser_challenge(status_code=sc, content_type=ct, head=h):
            return None
        return {"body": body, "content_type": ct, "suggested_filename": Path(urlparse(str(url or "")).path).name}

    def _try_cfscrape() -> Optional[Dict[str, Any]]:
        try:
            import cfscrape as _cfs
        except Exception:
            return None
        try:
            s = _cfs.create_scraper()
            resp = s.get(url, timeout=35, headers=headers)
        except Exception:
            return None
        sc = int(getattr(resp, "status_code", 599) or 599)
        ct = str(getattr(resp, "headers", {}).get("content-type") or "").lower()
        body = getattr(resp, "content", b"") or b""
        h = body[:1024].decode("latin1", errors="ignore")
        if sc >= 400 or _looks_like_browser_challenge(status_code=sc, content_type=ct, head=h):
            return None
        return {"body": body, "content_type": ct, "suggested_filename": Path(urlparse(str(url or "")).path).name}

    result = _try_cloudscraper()
    if result is not None:
        return result
    return _try_cfscrape()


async def _download_document_bytes_via_page_fetch(page: Any, url: str) -> Optional[Dict[str, Any]]:
    try:
        fetched = await page.evaluate(
            """
            async (targetUrl) => {
              const response = await fetch(targetUrl, { credentials: 'include' });
              const buffer = await response.arrayBuffer();
              return {
                ok: response.ok,
                status: response.status,
                contentType: response.headers.get('content-type') || '',
                contentDisposition: response.headers.get('content-disposition') || '',
                bodyBytes: Array.from(new Uint8Array(buffer)),
              };
            }
            """,
            url,
        )
    except Exception:
        return None

    if not isinstance(fetched, dict) or not fetched.get("ok"):
        return None

    body_values = fetched.get("bodyBytes") or []
    try:
        body = bytes(body_values)
    except Exception:
        return None
    if not body:
        return None

    content_type = str(fetched.get("contentType") or "").strip().lower()
    suggested_filename = Path(urlparse(str(url or "")).path).name
    if not content_type:
        lowered_name = suggested_filename.lower()
        if lowered_name.endswith(".pdf"):
            content_type = "application/pdf"
        elif lowered_name.endswith(".rtf"):
            content_type = "application/rtf"
        else:
            content_type = "application/octet-stream"

    return {
        "body": body,
        "content_type": content_type,
        "suggested_filename": suggested_filename,
    }


async def _download_document_bytes_via_playwright(url: str) -> Optional[Dict[str, Any]]:
    try:
        from playwright.async_api import async_playwright
    except Exception:
        return None

    referer = _pdf_request_headers(url).get("Referer") or ""
    browser_user_agent = _pdf_request_headers(url).get("User-Agent") or (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/123.0 Safari/537.36"
    )

    async def _attempt_download(p: Any, *, persistent_profile: bool) -> Optional[Dict[str, Any]]:
        browser = None
        if persistent_profile:
            profile_dir = _playwright_persistent_profile_dir()
            profile_dir.mkdir(parents=True, exist_ok=True)
            context = await p.chromium.launch_persistent_context(
                user_data_dir=str(profile_dir),
                headless=_playwright_headless_enabled(),
                accept_downloads=True,
                user_agent=browser_user_agent,
                locale="en-US",
                viewport={"width": 1440, "height": 900},
            )
            page = context.pages[0] if context.pages else await context.new_page()
        else:
            browser = await p.chromium.launch(headless=_playwright_headless_enabled())
            context = await browser.new_context(
                accept_downloads=True,
                user_agent=browser_user_agent,
                locale="en-US",
                viewport={"width": 1440, "height": 900},
            )
            page = await context.new_page()
        try:
            await _apply_playwright_session_state(context, page, url)
            download = None
            if referer and referer != url:
                try:
                    await page.goto(referer, wait_until="domcontentloaded", timeout=30000)
                except Exception:
                    pass
                fetched = await _download_document_bytes_via_page_fetch(page, url)
                if fetched is not None:
                    return fetched

            link_selector = f'a[href="{url}"]'
            try:
                locator = page.locator(link_selector).first
                if await locator.count() > 0:
                    async with page.expect_download(timeout=45000) as download_info:
                        await locator.click()
                    download = await download_info.value
            except Exception:
                download = None

            if download is None:
                try:
                    async with page.expect_download(timeout=45000) as download_info:
                        await page.goto(url, wait_until="domcontentloaded", timeout=45000)
                    download = await download_info.value
                except Exception:
                    download = None

            if download is None:
                fetched = await _download_document_bytes_via_page_fetch(page, url)
                if fetched is not None:
                    return fetched
                return None

            download_path = await download.path()
            if not download_path:
                return None
            body = Path(download_path).read_bytes()
            suggested_filename = str(getattr(download, "suggested_filename", "") or "")
            content_type = "application/octet-stream"
            lowered_name = suggested_filename.lower()
            if lowered_name.endswith(".pdf"):
                content_type = "application/pdf"
            elif lowered_name.endswith(".rtf"):
                content_type = "application/rtf"
            elif lowered_name.endswith(".docx"):
                content_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            return {
                "body": body,
                "content_type": content_type,
                "suggested_filename": suggested_filename,
            }
        finally:
            await context.close()
            if browser is not None:
                await browser.close()

    try:
        async with async_playwright() as p:
            attempt_modes = [_use_persistent_playwright_profile()]
            if attempt_modes[0]:
                attempt_modes.append(False)
            for persistent_profile in attempt_modes:
                fetched = await _attempt_download(p, persistent_profile=persistent_profile)
                if fetched is not None:
                    return fetched
    except Exception:
        return None


def _title_from_extracted_pdf_text(*, text: str, url: str) -> str:
    for line in str(text or "").splitlines():
        cleaned = re.sub(r"\s+", " ", line).strip()
        if len(cleaned) >= 12:
            return cleaned[:240]
    path = Path(urlparse(str(url or "").path).name)
    stem = re.sub(r"[_-]+", " ", path.stem).strip()
    return stem[:240] if stem else str(url or "").strip()[:240]


def _title_from_extracted_rtf_text(*, text: str, url: str) -> str:
    return _title_from_extracted_pdf_text(text=text, url=url)


def _title_from_extracted_docx_text(*, text: str, url: str) -> str:
    return _title_from_extracted_pdf_text(text=text, url=url)


def _trim_arizona_official_document_chrome(*, text: str, url: str, title: str = "") -> str:
    parsed = urlparse(str(url or "").strip())
    if parsed.netloc.lower() != "apps.azsos.gov" or not _AZ_OFFICIAL_DOCUMENT_PATH_RE.search(parsed.path or ""):
        return str(text or "").strip()

    normalized_text = str(text or "").strip()
    if not normalized_text:
        return normalized_text

    lines = [re.sub(r"\s+", " ", line).strip() for line in normalized_text.splitlines()]
    cleaned_lines = [line for line in lines if line]
    if not cleaned_lines:
        return normalized_text

    title_line_re = re.compile(r"^TITLE\s+\d+\.\s+", re.IGNORECASE)
    chapter_line_re = re.compile(r"^CHAPTER\s+\d+\.\s+", re.IGNORECASE)
    subchapter_line_re = re.compile(r"^SUBCHAPTER\s+[A-Z]\.\s+", re.IGNORECASE)
    article_line_re = re.compile(r"^ARTICLE\s+(?:\d+|[IVXLCDM]+)\.\s+", re.IGNORECASE)
    rule_line_re = re.compile(r"^R\d{1,2}-[A-Za-z0-9.-]+\.\s*", re.IGNORECASE)
    non_body_line_re = re.compile(
        r"^(?:Historical Note|Section|Title\s+\d+(?:\.|\b).*|CHAPTER\s+\d+\..*|SUBCHAPTER\s+[A-Z]\..*|ARTICLE\s+(?:\d+|[IVXLCDM]+)\..*|R\d{1,2}-[A-Za-z0-9.-]+\..*|\d+)$",
        re.IGNORECASE,
    )

    substantive_rule_index: Optional[int] = None
    for index, line in enumerate(cleaned_lines):
        if not rule_line_re.match(line):
            continue
        next_nonempty = ""
        for next_index in range(index + 1, len(cleaned_lines)):
            candidate = cleaned_lines[next_index]
            if candidate:
                next_nonempty = candidate
                break
        if next_nonempty and not non_body_line_re.match(next_nonempty):
            substantive_rule_index = index
            break

    if substantive_rule_index is None:
        return normalized_text

    start_index = substantive_rule_index
    for index in range(substantive_rule_index - 1, max(-1, substantive_rule_index - 41), -1):
        line = cleaned_lines[index]
        if title_line_re.match(line):
            start_index = index
            break
        if chapter_line_re.match(line) or subchapter_line_re.match(line) or article_line_re.match(line):
            start_index = index

    end_index = len(cleaned_lines)
    for index in range(start_index, len(cleaned_lines)):
        line = cleaned_lines[index]
        if _RTF_MARKER_LINE_RE.fullmatch(line):
            end_index = index
            break
        if line.count(";") >= 3 and _RTF_STYLE_CATALOG_LINE_RE.search(line):
            end_index = index
            break

    trimmed = "\n".join(cleaned_lines[start_index:end_index]).strip()
    return trimmed or normalized_text


def _title_from_arizona_official_document_text(*, text: str, url: str) -> str:
    parsed = urlparse(str(url or "").strip())
    if parsed.netloc.lower() != "apps.azsos.gov" or not _AZ_OFFICIAL_DOCUMENT_PATH_RE.search(parsed.path or ""):
        return ""
    title_line_re = re.compile(r"^TITLE\s+\d+\.\s+", re.IGNORECASE)
    rule_line_re = re.compile(r"^R\d{1,2}-[A-Za-z0-9.-]+\.\s*", re.IGNORECASE)
    non_body_line_re = re.compile(
        r"^(?:Historical Note|Section|Title\s+\d+(?:\.|\b).*|CHAPTER\s+\d+\..*|SUBCHAPTER\s+[A-Z]\..*|ARTICLE\s+(?:\d+|[IVXLCDM]+)\..*|R\d{1,2}-[A-Za-z0-9.-]+\..*|\d+)$",
        re.IGNORECASE,
    )
    title_candidates: List[tuple[int, str]] = []
    substantive_rule_index: Optional[int] = None

    for index, line in enumerate(str(text or "").splitlines()):
        cleaned = re.sub(r"\s+", " ", line).strip()
        if not cleaned:
            continue
        if title_line_re.match(cleaned):
            title_candidates.append((index, cleaned[:240]))
        if substantive_rule_index is None and rule_line_re.match(cleaned):
            next_nonempty = ""
            for next_line in str(text or "").splitlines()[index + 1 :]:
                next_nonempty = re.sub(r"\s+", " ", next_line).strip()
                if next_nonempty:
                    break
            if next_nonempty and not non_body_line_re.match(next_nonempty):
                substantive_rule_index = index

    if substantive_rule_index is not None:
        for index, candidate in reversed(title_candidates):
            if index <= substantive_rule_index:
                return candidate

    if title_candidates:
        return title_candidates[0][1]
    return ""


def _looks_like_bad_rtf_title(title: str) -> bool:
    value = re.sub(r"\s+", " ", str(title or "")).strip()
    if not value:
        return True
    if _RTF_CONTENT_PREFIX_RE.search(value[:256]):
        return True
    if _RTF_MARKER_LINE_RE.fullmatch(value):
        return True
    if value.lower().startswith(("(authority:", "authority:")):
        return True
    if value.lower().startswith(("please note that the chapter", "this is an unofficial version")):
        return True
    if re.match(r"^\d+\s+A\.A\.C\.\s+\d+(?:\|.*)?$", value, re.IGNORECASE):
        return True
    if _RTF_STYLE_CATALOG_LINE_RE.search(value) and value.count(";") >= 3:
        return True
    if len(value.split()) >= 18 and not re.match(r"^(?:title|chapter|article|section|rule|r\d{1,2}-\d{1,2}-\d{2,4})\b", value, re.IGNORECASE):
        return True
    return False


def _should_replace_arizona_official_title(*, current_title: str, recovered_title: str) -> bool:
    current_value = re.sub(r"\s+", " ", str(current_title or "")).strip()
    recovered_value = re.sub(r"\s+", " ", str(recovered_title or "")).strip()
    if not recovered_value:
        return False
    if not current_value:
        return True
    if current_value.lower() == recovered_value.lower():
        return False
    if _looks_like_bad_rtf_title(current_value):
        return True
    if re.match(r"^title\s+\d+\s*,\s*ch\.?\s*\d+\b", current_value, re.IGNORECASE):
        return True
    if recovered_value.lower().startswith("title ") and not re.match(r"^title\s+\d+\.\s+", current_value, re.IGNORECASE):
        return True
    return False


def _title_from_california_westlaw_document_text(*, text: str, url: str) -> str:
    parsed = urlparse(str(url or "").strip())
    if parsed.netloc.lower() != "govt.westlaw.com" or not parsed.path.lower().startswith("/calregs/document/"):
        return ""

    normalized_text = str(text or "").strip()
    if not normalized_text:
        return ""

    section_match = re.search(r"(§\s*[\w.-]+\.?\s+[^\n]{1,220}?\.)", normalized_text)
    if section_match:
        return re.sub(r"\s+", " ", section_match.group(1)).strip()[:240]

    for line in normalized_text.splitlines():
        cleaned = re.sub(r"\s+", " ", line).strip()
        if not cleaned:
            continue
        if re.match(r"^(?:§\s*[\w.-]+\.?|Article\s+[\w.-]+\.?|Chapter\s+[\w.-]+\.?|Title\s+[\w.-]+\.?)\b", cleaned, re.IGNORECASE):
            return cleaned[:240]

    return ""


def _title_from_south_dakota_rule_text(*, text: str, url: str) -> str:
    if not _south_dakota_rule_reference_from_url(url):
        return ""

    normalized_text = str(text or "").strip()
    if not normalized_text:
        return ""

    for line in normalized_text.splitlines():
        cleaned = re.sub(r"\s+", " ", line).strip()
        if not cleaned:
            continue
        if re.match(r"^(?:ARTICLE\s+\d{1,2}:\d{2}|CHAPTER\s+\d{1,2}:\d{2}:\d{2}|\d{1,2}:\d{2}:\d{2}(?::\d{2})?\.?)\b", cleaned, re.IGNORECASE):
            return cleaned[:240]

    return ""


def _trim_south_dakota_rule_document_chrome(*, text: str, url: str, title: str = "") -> str:
    if not _south_dakota_rule_reference_from_url(url):
        return str(text or "").strip()

    normalized_text = str(text or "").strip()
    if not normalized_text:
        return normalized_text

    lines = [re.sub(r"\s+", " ", line).strip() for line in normalized_text.splitlines()]
    cleaned_lines = [line for line in lines if line]
    if not cleaned_lines:
        return normalized_text

    start_index: Optional[int] = None
    rule_reference = _south_dakota_rule_reference_from_url(url)
    section_pattern = re.compile(r"^\d{1,2}:\d{2}:\d{2}(?::\d{2})?\.?")
    chapter_pattern = re.compile(r"^(?:ARTICLE\s+\d{1,2}:\d{2}|CHAPTER\s+\d{1,2}:\d{2}:\d{2})\b", re.IGNORECASE)
    generic_nav_markers = {
        "LEGISLATORS",
        "SESSION",
        "INTERIM",
        "LAWS",
        "ADMINISTRATIVE RULES",
        "BUDGET",
        "STUDENTS",
        "REFERENCES",
        "MYLRC +",
        "Administrative Rules List",
        "Current Register (PDF)",
        "Archived Registers",
        "Administrative Rules Manual",
        "Rules Review Committee",
        "Rules.sd.gov",
        "Administrative Rules Process (PDF)",
    }

    for index, line in enumerate(cleaned_lines):
        if rule_reference.count(":") >= 2 and section_pattern.match(line):
            start_index = index
            break
        if rule_reference.count(":") == 1 and chapter_pattern.match(line):
            start_index = index
            break

    if start_index is not None and start_index > 0:
        cleaned_lines = cleaned_lines[start_index:]

    filtered_lines: List[str] = []
    for line in cleaned_lines:
        if line in generic_nav_markers:
            continue
        if line.startswith("Current Register") or line.startswith("Administrative Rules Process"):
            continue
        filtered_lines.append(line)

    trimmed = "\n".join(filtered_lines).strip()
    return trimmed or normalized_text


def _trim_rhode_island_ricr_document_chrome(*, text: str, url: str, title: str = "") -> str:
    parsed = urlparse(str(url or "").strip())
    if parsed.netloc.lower() != "rules.sos.ri.gov" or not _RI_RICR_DETAIL_PATH_RE.match(parsed.path or ""):
        return str(text or "").strip()

    normalized_text = str(text or "").strip()
    if not normalized_text:
        return normalized_text

    normalized_title = re.sub(
        r"\s*-\s*Rhode\s+Island\s+Department\s+of\s+State\s*$",
        "",
        str(title or "").strip(),
        flags=re.IGNORECASE,
    ).strip()

    start_index: Optional[int] = None
    if normalized_title:
        title_index = normalized_text.find(normalized_title)
        if title_index >= 0:
            start_index = title_index

    if start_index is None:
        active_rule_match = re.search(
            r"(?:^|\n)(\d{3}-RICR-\d{2}-\d{2}-\d+\s+ACTIVE\s+RULE)\b",
            normalized_text,
            re.IGNORECASE,
        )
        if active_rule_match:
            start_index = active_rule_match.start(1)

    if start_index is not None and start_index > 0:
        trimmed = normalized_text[start_index:].strip()
    else:
        trimmed = normalized_text

    end_markers = [
        "2002-Current Regulations",
        "Additional Links",
        "Powered by Google Translate",
        "Return to top",
    ]
    end_index: Optional[int] = None
    for marker in end_markers:
        marker_index = trimmed.find(marker)
        if marker_index >= 0 and (end_index is None or marker_index < end_index):
            end_index = marker_index
    if end_index is not None and end_index > 0:
        trimmed = trimmed[:end_index].strip()

    lines = [re.sub(r"\s+", " ", line).strip() for line in trimmed.splitlines()]
    cleaned_lines: List[str] = []
    seen_title = False
    seen_active_rule = False
    for line in lines:
        if not line:
            continue
        if re.match(r"^An Official Rhode Island State Website\.?$", line, re.IGNORECASE):
            continue
        if re.match(r"^Rhode Island Department of State$", line, re.IGNORECASE):
            continue
        if re.match(r"^Gregg M\. Amore$", line, re.IGNORECASE):
            continue
        if re.match(r"^Secretary of State$", line, re.IGNORECASE):
            continue
        if re.match(r"^Select Language$", line, re.IGNORECASE):
            continue
        if re.match(r"^Regulation TextOverviewRegulationHistoryRulemaking Documents$", line, re.IGNORECASE):
            continue
        if line in {"Regulation Text", "Overview", "Regulation", "History", "Rulemaking Documents"}:
            continue
        if re.search(r"(?:Subscribe to Notifications|Return to top|Powered by Google Translate|Image of the Rhode Island coat of arms)", line, re.IGNORECASE):
            continue
        if normalized_title and line == normalized_title:
            if seen_title:
                continue
            seen_title = True
        if re.match(r"^\d{3}-RICR-\d{2}-\d{2}-\d+\s+ACTIVE\s+RULE$", line, re.IGNORECASE):
            if seen_active_rule:
                continue
            seen_active_rule = True
        cleaned_lines.append(line)

    cleaned = "\n".join(cleaned_lines).strip()
    return cleaned or trimmed


def _trim_california_westlaw_document_chrome(*, text: str, url: str, title: str = "") -> str:
    parsed = urlparse(str(url or "").strip())
    if parsed.netloc.lower() != "govt.westlaw.com" or not parsed.path.lower().startswith("/calregs/document/"):
        return str(text or "").strip()

    normalized_text = str(text or "").strip()
    if not normalized_text:
        return normalized_text

    candidate_markers: List[str] = []
    normalized_title = str(title or "").strip()
    if normalized_title and "california code of regulations" not in normalized_title.lower():
        candidate_markers.append(normalized_title)

    extracted_title = _title_from_california_westlaw_document_text(text=normalized_text, url=url)
    if extracted_title and extracted_title not in candidate_markers:
        candidate_markers.append(extracted_title)

    start_index: Optional[int] = None
    for marker in candidate_markers:
        marker_index = normalized_text.find(marker)
        if marker_index >= 0 and (start_index is None or marker_index < start_index):
            start_index = marker_index

    if start_index is None:
        section_match = re.search(
            r"(?:^|\n)(§\s*[\w.-]+\.?\s+[^\n]{1,220}?\.|Article\s+[\w.-]+\.?[^\n]{0,220}|Chapter\s+[\w.-]+\.?[^\n]{0,220}|Title\s+[\w.-]+\.?[^\n]{0,220})",
            normalized_text,
            re.IGNORECASE,
        )
        if section_match:
            start_index = section_match.start(1)

    if start_index is None or start_index <= 0:
        trimmed = normalized_text
    else:
        trimmed = normalized_text[start_index:].strip()

    if not trimmed:
        return normalized_text

    lines = [re.sub(r"\s+", " ", line).strip() for line in trimmed.splitlines()]
    cleaned_lines: List[str] = []
    seen_heading = False
    heading_line = candidate_markers[0] if candidate_markers else ""
    heading_is_section = bool(re.match(r"^§\s*[\w.-]+", heading_line, re.IGNORECASE))
    for line in lines:
        if not line:
            continue
        if not seen_heading:
            cleaned_lines.append(line)
            seen_heading = True
            continue
        if heading_is_section:
            if heading_line and line == heading_line:
                continue
            if _CA_WESTLAW_DOCUMENT_BREADCRUMB_LINE_RE.match(line):
                continue
            if re.match(r"^\d+\s+CCR\s+§\s*[\w.-]+$", line, re.IGNORECASE):
                continue
            if line.lower() == "currentness":
                continue
        if _CA_WESTLAW_DOCUMENT_BOILERPLATE_LINE_RE.match(line):
            continue
        cleaned_lines.append(line)

    cleaned = "\n".join(cleaned_lines).strip()
    return cleaned or trimmed


def _trim_indiana_iarp_document_chrome(*, text: str, url: str, title: str = "") -> str:
    parsed = urlparse(str(url or "").strip())
    if parsed.netloc.lower() != "iar.iga.in.gov" or not re.search(
        r"/code/(?:current|2006|2024)/\d+/\d+(?:\.\d+)?(?:/\d+(?:\.\d+)?)?",
        parsed.path or "",
        re.IGNORECASE,
    ):
        return str(text or "").strip()

    normalized_text = str(text or "").strip()
    if not normalized_text:
        return normalized_text

    lines = [re.sub(r"\s+", " ", line).strip() for line in normalized_text.splitlines()]
    cleaned_lines = [line for line in lines if line]
    if not cleaned_lines:
        return normalized_text

    normalized_title = re.sub(r"\s*\|\s*IARP\s*$", "", str(title or "").strip(), flags=re.IGNORECASE).strip()
    title_match = re.match(
        r"Title\s+(?P<title_num>\d+),\s*ARTICLE\s+(?P<article_num>\d+(?:\.\d+)?)\.?\s*(?P<subject>.+)$",
        normalized_title,
        re.IGNORECASE,
    )
    title_num = title_match.group("title_num") if title_match else ""
    article_line_re: Optional[re.Pattern[str]] = None
    if title_match:
        subject_pattern = re.sub(r"\\ ", r"\\s+", re.escape(title_match.group("subject").strip()))
        article_line_re = re.compile(
            rf"^ARTICLE\s+{re.escape(title_match.group('article_num'))}\.?\s+{subject_pattern}$",
            re.IGNORECASE,
        )

    footer_index: Optional[int] = None
    for index, line in enumerate(cleaned_lines):
        if _INDIANA_IARP_FOOTER_LINE_RE.match(line):
            footer_index = index
            break
    if footer_index is not None:
        cleaned_lines = cleaned_lines[:footer_index]

    body_index: Optional[int] = None
    detail_heading_index: Optional[int] = None
    for index, line in enumerate(cleaned_lines):
        if re.match(r"^\d+\s+IAC\s+[\w.-]+\b", line, re.IGNORECASE):
            body_index = index
            break

    if body_index is None:
        for index, line in enumerate(cleaned_lines):
            if _INDIANA_IARP_BODY_LINE_RE.match(line):
                body_index = index
                break

    if article_line_re is not None:
        article_matches = [index for index, line in enumerate(cleaned_lines) if article_line_re.match(line)]
        if len(article_matches) >= 2:
            detail_heading_index = article_matches[1]
        elif article_matches:
            detail_heading_index = article_matches[0]

    if body_index is None and detail_heading_index is not None:
        body_index = detail_heading_index

    if body_index is None:
        while cleaned_lines and (
            cleaned_lines[0].lower() in {
                "indiana administrative rules and policies",
                "home",
                "indiana register",
                "administrative code",
                "myiar",
                "current",
            }
            or _INDIANA_IARP_TOOLBAR_LINE_RE.match(cleaned_lines[0])
        ):
            cleaned_lines.pop(0)
        trimmed = "\n".join(cleaned_lines).strip()
        return trimmed or normalized_text

    trimmed_lines = cleaned_lines[body_index:]
    filtered_lines: List[str] = []
    article_heading_seen = False
    title_heading_seen = False
    for line in trimmed_lines:
        if _INDIANA_IARP_TOOLBAR_LINE_RE.match(line):
            continue
        if article_line_re is not None and article_line_re.match(line):
            if article_heading_seen:
                continue
            article_heading_seen = True
        if title_num and re.match(rf"^TITLE\s+{re.escape(title_num)}\b", line, re.IGNORECASE):
            if title_heading_seen:
                continue
            if article_heading_seen:
                continue
            title_heading_seen = True
        filtered_lines.append(line)

    trimmed = "\n".join(filtered_lines).strip()
    return trimmed or normalized_text


async def _normalize_candidate_document_content(*, url: str, title: str, text: str) -> tuple[str, str]:
    normalized_title = str(title or "").strip()
    normalized_text = str(text or "").strip()
    if not normalized_text:
        return normalized_title, normalized_text

    if _is_rtf_candidate_url(url) and _RTF_CONTENT_PREFIX_RE.search(normalized_text[:1024]):
        extracted_text = await _extract_text_from_rtf_bytes_with_processor(
            normalized_text.encode("latin1", errors="ignore"),
            source_url=url,
        )
        extracted_text = str(extracted_text or "").strip()
        if extracted_text and not _RTF_CONTENT_PREFIX_RE.search(extracted_text[:1024]):
            normalized_text = extracted_text
            extracted_title = _title_from_extracted_rtf_text(text=normalized_text, url=url)
            if extracted_title and _looks_like_bad_rtf_title(normalized_title):
                normalized_title = extracted_title
            elif not normalized_title or _RTF_CONTENT_PREFIX_RE.search(normalized_title[:1024]):
                normalized_title = extracted_title

    if (
        normalized_title.lower() == "view document - california code of regulations"
        or normalized_title.lower() == "california code of regulations"
    ):
        california_title = _title_from_california_westlaw_document_text(text=normalized_text, url=url)
        if california_title:
            normalized_title = california_title

    if "south dakota legislature" in normalized_title.lower() or normalized_title.lower().startswith("administrative rule "):
        south_dakota_title = _title_from_south_dakota_rule_text(text=normalized_text, url=url)
        if south_dakota_title:
            normalized_title = south_dakota_title

    normalized_text = _trim_california_westlaw_document_chrome(
        text=normalized_text,
        url=url,
        title=normalized_title,
    )

    parsed = urlparse(str(url or "").strip())
    if parsed.netloc.lower() == "sdlegislature.gov" and _south_dakota_rule_reference_from_url(url):
        normalized_text = _trim_south_dakota_rule_document_chrome(
            text=normalized_text,
            url=url,
            title=normalized_title,
        )
    if parsed.netloc.lower() == "rules.sos.ri.gov" and _RI_RICR_DETAIL_PATH_RE.match(parsed.path or ""):
        normalized_title = re.sub(
            r"\s*-\s*Rhode\s+Island\s+Department\s+of\s+State\s*$",
            "",
            normalized_title,
            flags=re.IGNORECASE,
        ).strip()
        normalized_text = _trim_rhode_island_ricr_document_chrome(
            text=normalized_text,
            url=url,
            title=normalized_title,
        )

    if parsed.netloc.lower() == "iar.iga.in.gov" and re.search(
        r"/code/(?:current|2006|2024)/\d+/\d+(?:\.\d+)?(?:/\d+(?:\.\d+)?)?",
        parsed.path or "",
        re.IGNORECASE,
    ):
        normalized_title = re.sub(r"\s*\|\s*IARP\s*$", "", normalized_title, flags=re.IGNORECASE).strip()
        normalized_text = _trim_indiana_iarp_document_chrome(
            text=normalized_text,
            url=url,
            title=normalized_title,
        )

    if _looks_like_arizona_official_rule_document(text=normalized_text, title=normalized_title, url=url):
        arizona_original_text = normalized_text
        normalized_text = _trim_arizona_official_document_chrome(
            text=normalized_text,
            url=url,
            title=normalized_title,
        )
        arizona_title = _title_from_arizona_official_document_text(text=normalized_text, url=url)
        if not arizona_title:
            arizona_title = _title_from_arizona_official_document_text(text=arizona_original_text, url=url)
        if _should_replace_arizona_official_title(
            current_title=normalized_title,
            recovered_title=arizona_title,
        ):
            normalized_title = arizona_title

    return normalized_title, normalized_text


def _document_format_for_url(url: str) -> str:
    if _is_pdf_candidate_url(url):
        return "pdf"
    if _is_rtf_candidate_url(url):
        return "rtf"
    if _is_docx_candidate_url(url):
        return "docx"
    return "html"


def _extract_text_from_pdf_bytes_natively(pdf_bytes: bytes) -> str:
    if not pdf_bytes:
        return ""

    try:
        from pypdf import PdfReader
    except Exception:
        return ""

    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        text_parts: List[str] = []
        for page in reader.pages:
            try:
                page_text = str(page.extract_text() or "").strip()
            except Exception:
                page_text = ""
            if page_text:
                text_parts.append(page_text)
        extracted_text = "\n\n".join(text_parts).strip()
        return extracted_text if len(extracted_text) >= 80 else ""
    except Exception:
        return ""


async def _extract_text_from_pdf_bytes_with_processor(pdf_bytes: bytes, *, source_url: str) -> str:
    if not pdf_bytes:
        return ""

    extracted_text = _extract_text_from_pdf_bytes_natively(pdf_bytes)
    if extracted_text:
        return extracted_text

    try:
        from ipfs_datasets_py.processors.specialized.pdf import PDFProcessor
    except Exception:
        return ""

    temp_path: Optional[Path] = None
    try:
        with NamedTemporaryFile(suffix=".pdf", delete=False) as handle:
            handle.write(pdf_bytes)
            temp_path = Path(handle.name)

        # Admin-rules PDF extraction only needs native page text and optional OCR
        # fallback. Avoid bootstrapping storage, GraphRAG, and embedding/LLM
        # components here because they can dominate fetch time for simple text
        # extraction workloads.
        processor = PDFProcessor(
            enable_audit=False,
            mock_dict={
                "storage": object(),
                "integrator": object(),
                "ocr_engine": object(),
                "optimizer": object(),
            },
        )
        decomposed_content = await processor._decompose_pdf(temp_path)

        text_parts: List[str] = []
        for page_data in decomposed_content.get("pages") or []:
            text_blocks = page_data.get("text_blocks") or []
            try:
                page_text = processor._extract_native_text(text_blocks)
            except Exception:
                page_text = ""
            page_text = str(page_text or "").strip()
            if page_text:
                text_parts.append(page_text)

        if text_parts:
            return "\n\n".join(text_parts).strip()

        try:
            ocr_results = await processor._process_ocr(decomposed_content)
        except Exception:
            ocr_results = {}

        for page_ocr in (ocr_results or {}).values():
            for image_result in page_ocr or []:
                ocr_text = str((image_result or {}).get("text") or "").strip()
                if ocr_text:
                    text_parts.append(ocr_text)

        return "\n\n".join(text_parts).strip()
    except Exception:
        return ""
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except Exception:
                pass


async def _extract_text_from_rtf_bytes_with_processor(rtf_bytes: bytes, *, source_url: str) -> str:
    if not rtf_bytes:
        return ""

    try:
        preview = rtf_bytes[:8192].decode("latin1", errors="ignore")
    except Exception:
        preview = ""
    preview_stripped = preview.lstrip()
    if preview_stripped.startswith("<") and _BROWSER_CHALLENGE_HTML_RE.search(preview):
        return ""

    def _trim_leading_rtf_noise(value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return ""

        lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
        lines = [line for line in lines if line]
        if len(lines) <= 3:
            return "\n".join(lines).strip()

        candidate_index: Optional[int] = None
        for index, line in enumerate(lines[:120]):
            if _RTF_LEADING_CONTENT_LINE_RE.search(line) or _RULE_BODY_SIGNAL_RE.search(line):
                candidate_index = index
                break

        if candidate_index is None or candidate_index <= 0:
            return "\n".join(lines).strip()

        trimmed = "\n".join(lines[candidate_index:]).strip()
        if len(trimmed) < 200:
            return "\n".join(lines).strip()
        return trimmed

    def _repair_split_rtf_words(value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return ""

        intact_words = {
            match.group(0).lower()
            for match in re.finditer(r"\b[A-Za-z]{4,}\b", text)
        }

        def _replace(match: re.Match[str]) -> str:
            left = match.group(1)
            right = match.group(2)
            if len(left) > 4 and len(right) > 4:
                return match.group(0)

            joined = f"{left}{right}"
            joined_lower = joined.lower()
            if joined_lower not in intact_words and joined_lower not in _RTF_COMMON_JOINED_WORDS:
                return match.group(0)

            if left.isupper() and right.isupper():
                return joined.upper()
            if left[:1].isupper() and right[:1].islower():
                return joined[:1].upper() + joined[1:]
            return joined

        repaired = text
        for _ in range(2):
            updated = _RTF_SPLIT_WORD_RE.sub(_replace, repaired)
            if updated == repaired:
                break
            repaired = updated

        def _case_preserving_common_word(match: re.Match[str], joined_word: str) -> str:
            collapsed = re.sub(r"[^A-Za-z]", "", match.group(0))
            if collapsed.isupper():
                return joined_word.upper()
            if collapsed[:1].isupper():
                return joined_word[:1].upper() + joined_word[1:]
            return joined_word

        for joined_word in sorted(_RTF_COMMON_JOINED_WORDS, key=len, reverse=True):
            for split_index in range(1, len(joined_word)):
                pattern = re.compile(
                    rf"\b{re.escape(joined_word[:split_index])}(?: |\n){re.escape(joined_word[split_index:])}\b",
                    re.IGNORECASE,
                )
                repaired = pattern.sub(
                    lambda match, joined_word=joined_word: _case_preserving_common_word(match, joined_word),
                    repaired,
                )
        return repaired

    def _strip_embedded_binary_artifacts(value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return ""

        cleaned_lines: List[str] = []
        for raw_line in text.splitlines():
            line = re.sub(r"\s+", " ", str(raw_line or "")).strip()
            if not line:
                continue
            if _RTF_MARKER_LINE_RE.fullmatch(line):
                continue
            if _RTF_ARCHIVE_ARTIFACT_RE.search(line):
                continue
            if line.count(";") >= 8 and _RTF_STYLE_CATALOG_LINE_RE.search(line):
                continue

            line = _RTF_INLINE_BINARY_BLOB_RE.sub(" ", line)
            line = re.sub(r"\s+", " ", line).strip()
            if not line:
                continue

            compact = re.sub(r"[^0-9A-Fa-f]", "", line)
            compact_ratio = (len(compact) / max(len(line), 1)) if line else 0.0
            if len(compact) >= 48 and compact_ratio >= 0.7:
                continue

            cleaned_lines.append(line)

        return "\n".join(cleaned_lines).strip()

    def _fallback_extract_text(value: str) -> str:
        if not value:
            return ""

        value = re.sub(
            r"\\'([0-9a-fA-F]{2})",
            lambda match: bytes.fromhex(match.group(1)).decode("latin1", errors="ignore"),
            value,
        )

        def _decode_unicode(match: re.Match[str]) -> str:
            try:
                codepoint = int(match.group(1))
            except Exception:
                return ""
            if codepoint < 0:
                codepoint += 65536
            try:
                return chr(codepoint)
            except Exception:
                return ""

        value = re.sub(r"\\u(-?\d+)\??", _decode_unicode, value)
        value = re.sub(r"\\(?:par[d]?|line)\b", "\n", value)
        value = re.sub(r"\\tab\b", " ", value)
        value = value.replace("\\*", " ")
        value = re.sub(r"\\([{}\\])", r"\1", value)
        value = re.sub(r"\\[a-zA-Z]+-?\d* ?", " ", value)
        value = value.replace("{", " ").replace("}", " ")
        value = re.sub(r'HYPERLINK\s+"[^"]+"', " ", value, flags=re.IGNORECASE)
        value = re.sub(r"\bPAGE\s+-?\d+\b", " ", value, flags=re.IGNORECASE)

        lines = []
        for raw_line in value.splitlines():
            cleaned = re.sub(r"\s+", " ", raw_line).strip()
            if cleaned:
                lines.append(cleaned)
        return _repair_split_rtf_words(
            _strip_embedded_binary_artifacts(_trim_leading_rtf_noise("\n".join(lines).strip()))
        )

    def _fallback_extract() -> str:
        try:
            value = rtf_bytes.decode("latin1", errors="ignore")
        except Exception:
            return ""
        return _fallback_extract_text(value)

    def _score_extracted_text(value: str) -> float:
        text = str(value or "").strip()
        if not text:
            return float("-inf")
        text = _strip_embedded_binary_artifacts(text)
        if not text:
            return float("-inf")
        prefix = text[:4000]
        legal_hits = len(re.findall(r"\b(?:chapter|article|title|section|rule|supp\.)\b|R\d{1,2}-\d{1,2}-\d{2,4}", prefix, re.IGNORECASE))
        noise_hits = len(_RTF_EXTRACTION_NOISE_RE.findall(prefix))
        leading_noise_penalty = 12.0 if _RTF_EXTRACTION_NOISE_RE.search(text[:600]) else 0.0
        leading_signal_bonus = 6.0 if _RTF_LEADING_CONTENT_LINE_RE.search(text[:600]) else 0.0
        return float(legal_hits * 8 - noise_hits * 5 - leading_noise_penalty + leading_signal_bonus + min(len(text), 12000) / 1000.0)

    def _best_fallback_extract() -> str:
        try:
            value = rtf_bytes.decode("latin1", errors="ignore")
        except Exception:
            return ""
        candidates = [_fallback_extract_text(value)]
        content_start_match = _RTF_CONTENT_START_RE.search(value)
        if content_start_match:
            candidates.append(_fallback_extract_text(value[content_start_match.start() :]))
        return max(candidates, key=_score_extracted_text)

    try:
        from ipfs_datasets_py.processors.file_converter import RTFExtractor
    except Exception:
        return _best_fallback_extract()

    temp_path: Optional[Path] = None
    try:
        with NamedTemporaryFile(suffix=".rtf", delete=False) as handle:
            handle.write(rtf_bytes)
            temp_path = Path(handle.name)

        extractor = RTFExtractor()
        result = await asyncio.to_thread(extractor.extract, temp_path)
        extracted_text = _strip_embedded_binary_artifacts(
            _trim_leading_rtf_noise(str(getattr(result, "text", "") or "").strip())
        )
        fallback_text = _best_fallback_extract()
        if getattr(result, "success", False) and extracted_text:
            extracted_text = _repair_split_rtf_words(
                _strip_embedded_binary_artifacts(_trim_leading_rtf_noise(extracted_text))
            )
            if _score_extracted_text(fallback_text) > _score_extracted_text(extracted_text):
                return fallback_text
            return extracted_text
        return fallback_text
    except Exception:
        return _best_fallback_extract()
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except Exception:
                pass


async def _fetch_html_bypassing_challenge(url: str) -> Optional[Dict[str, Any]]:
    """Return rendered text for a URL that is behind a browser challenge.

    Fallback order:
      1. ``cloudscraper`` (already handles many CF challenges via JS token emulation)
      2. ``cfscrape`` (legacy CF bypass library)
      3. Wayback Machine snapshot via :class:`UnifiedWebScraper`
      4. Common Crawl index via :class:`UnifiedWebScraper`

    Returns ``{text, html, source}`` or ``None``.
    """
    # --- 1 & 2: scraper-based bypass (binary-safe, returns bytes) ---------------
    doc_bytes = _download_document_bytes_via_cloudscraper(url)
    if doc_bytes is not None:
        body = doc_bytes.get("body") or b""
        body_text = body.decode("utf-8", errors="replace") if body else ""
        ct = doc_bytes.get("content_type") or ""
        if body_text.strip() and not _looks_like_browser_challenge(
            status_code=200, content_type=ct, head=body_text[:1024]
        ):
            return {"text": body_text, "html": body_text, "source": "cloudscraper"}

    # --- 3 & 4: archive fallback via UnifiedWebScraper --------------------------
    try:
        try:
            from ..web_archiving.unified_web_scraper import ScraperConfig, ScraperMethod, UnifiedWebScraper as _UWS
        except ImportError:
            from ipfs_datasets_py.processors.web_archiving.unified_web_scraper import ScraperConfig, ScraperMethod, UnifiedWebScraper as _UWS  # type: ignore[no-redef]
    except ImportError:
        return None

    for method in (ScraperMethod.WAYBACK_MACHINE, ScraperMethod.COMMON_CRAWL):
        try:
            _cfg = ScraperConfig(timeout=35, max_retries=1, extract_links=False, extract_text=True, fallback_enabled=False, preferred_methods=[method])
            _scraper = _UWS(_cfg)
            scraped = await _scraper.scrape(url, method=method)
            if getattr(scraped, "success", False):
                _text = str(getattr(scraped, "text", "") or "").strip()
                _html = str(getattr(scraped, "html", "") or "")
                if _text and not _looks_like_browser_challenge(
                    status_code=200, content_type="text/html", head=_text[:1024]
                ):
                    return {"text": _text, "html": _html, "source": str(getattr(method, "value", method))}
        except Exception:
            continue
    return None


async def _download_text_via_cloudflare_crawl(url: str) -> Optional[Dict[str, Any]]:
    """Retrieve rendered text from a URL via Cloudflare Browser Rendering API.

    Returns a dict with ``text``, ``html``, ``markdown``, ``record_url``, and
    cloudflare status fields, or ``None`` when unavailable or failed.
    If the CF crawl itself returns a challenge page (e.g. the target is behind
    a WAF), automatically falls back to :func:`_fetch_html_bypassing_challenge`.
    """
    cf = _cloudflare_browser_rendering_availability()
    if not cf.get("available"):
        return None

    account_id_env = cf.get("account_id_env") or ""
    api_token_env = cf.get("api_token_env") or ""
    account_id = str(os.getenv(account_id_env) or "").strip() if account_id_env else ""
    api_token = str(os.getenv(api_token_env) or "").strip() if api_token_env else ""
    if not account_id or not api_token:
        return None

    try:
        try:
            from ..web_archiving.cloudflare_browser_rendering_engine import (
                crawl_with_cloudflare_browser_rendering,
            )
        except ImportError:
            from ipfs_datasets_py.processors.web_archiving.cloudflare_browser_rendering_engine import (  # type: ignore[no-redef]
                crawl_with_cloudflare_browser_rendering,
            )
    except ImportError:
        return None

    try:
        result = await crawl_with_cloudflare_browser_rendering(
            url,
            account_id=account_id,
            api_token=api_token,
            formats=["markdown", "html"],
            render=True,
            depth=0,
            limit=1,
            timeout_seconds=60,
        )
    except Exception:
        return None

    if str(result.get("status") or "").lower() != "success":
        return None

    records = list(result.get("records") or [])
    if not records:
        return None

    record = records[0]
    markdown = str(record.get("markdown") or "").strip()
    html_text = str(record.get("html") or "").strip()
    text = markdown or html_text
    if not text:
        return None

    # If Cloudflare Rendering itself returned a challenge page (e.g. the target
    # host is protected by a different WAF layer), fall back to archive sources.
    if _looks_like_browser_challenge(status_code=200, content_type="text/html", head=text[:1024]):
        bypass = await _fetch_html_bypassing_challenge(url)
        if bypass is not None and not _looks_like_browser_challenge(
            status_code=200, content_type="text/html", head=(bypass.get("text") or "")[:1024]
        ):
            return {
                "text": bypass["text"],
                "html": bypass.get("html") or bypass["text"],
                "markdown": "",
                "record_url": url,
                "cloudflare_record_status": "bypassed",
                "cloudflare_job_status": bypass.get("source"),
            }
        return None

    return {
        "text": text,
        "html": html_text,
        "markdown": markdown,
        "record_url": str(record.get("url") or url),
        "cloudflare_record_status": record.get("status"),
        "cloudflare_job_status": result.get("job_status") or result.get("status"),
    }


async def _scrape_pdf_candidate_url(url: str, *, native_text_only: bool = False) -> Optional[Any]:
    if not _is_pdf_candidate_url(url):
        return None

    response = None
    try:
        response = requests.get(
            url,
            timeout=35,
            headers=_pdf_request_headers(url),
        )
    except Exception:
        response = None

    content_type = str(getattr(response, "headers", {}).get("content-type") or "").lower()
    body = getattr(response, "content", b"") or b""
    head = body[:1024].decode("latin1", errors="ignore")
    used_browser_download = False
    used_cloudscraper = False

    if response is None or _looks_like_browser_challenge(
        status_code=int(getattr(response, "status_code", 599) or 599),
        content_type=content_type,
        head=head,
    ):
        downloaded = _download_document_bytes_via_cloudscraper(url)
        if downloaded is not None:
            used_cloudscraper = True
        else:
            downloaded = await _download_document_bytes_via_playwright(url)
        if downloaded is None:
            cf_text = await _download_text_via_cloudflare_crawl(url)
            if cf_text and len(cf_text.get("text") or "") > 100:
                extracted = str(cf_text.get("text") or "").strip()
                method_value = "pdf_native_text_cloudflare_rendering" if native_text_only else "pdf_processor_cloudflare_rendering"
                return SimpleNamespace(
                    url=url,
                    title=_title_from_extracted_pdf_text(text=extracted, url=url),
                    text=extracted,
                    html=cf_text.get("html") or "",
                    links=[],
                    success=True,
                    method_used=method_value,
                    extraction_provenance={
                        "method": method_value,
                        "cloudflare_record_status": cf_text.get("cloudflare_record_status"),
                        "cloudflare_job_status": cf_text.get("cloudflare_job_status"),
                    },
                )
            return None
        body = downloaded.get("body") or b""
        content_type = str(downloaded.get("content_type") or "").lower()
        head = body[:1024].decode("latin1", errors="ignore")
        used_browser_download = not used_cloudscraper
    elif int(getattr(response, "status_code", 599) or 599) >= 400:
        return None

    if not body:
        return None
    if content_type.startswith("text/html") and _BAD_DISCOVERY_TEXT_RE.search(head):
        return None
    if "application/pdf" not in content_type and not _PDF_BINARY_HEADER_RE.search(head):
        return None

    extracted_text = (
        _extract_text_from_pdf_bytes_natively(body)
        if native_text_only
        else await _extract_text_from_pdf_bytes_with_processor(body, source_url=url)
    )
    extracted_text = str(extracted_text or "").strip()
    if not extracted_text:
        return None

    base_method = "pdf_native_text" if native_text_only else "pdf_processor"
    method_value = (
        f"{base_method}_cloudscraper"
        if used_cloudscraper
        else f"{base_method}_playwright_download" if used_browser_download else base_method
    )
    return SimpleNamespace(
        url=url,
        title=_title_from_extracted_pdf_text(text=extracted_text, url=url),
        text=extracted_text,
        html="",
        links=[],
        success=True,
        method_used=method_value,
        extraction_provenance={
            "method": method_value,
            "source_url": url,
            "content_type": content_type,
            "used_cloudscraper": used_cloudscraper,
            "used_browser_download": used_browser_download,
            "body_bytes": len(body),
        },
    )


async def _scrape_pdf_candidate_url_with_processor(url: str) -> Optional[Any]:
    return await _scrape_pdf_candidate_url(url, native_text_only=False)


async def _scrape_pdf_candidate_url_with_native_text(url: str) -> Optional[Any]:
    return await _scrape_pdf_candidate_url(url, native_text_only=True)


async def _scrape_rtf_candidate_url_with_processor(url: str) -> Optional[Any]:
    if not _is_rtf_candidate_url(url):
        return None

    response = None
    try:
        response = requests.get(
            url,
            timeout=35,
            headers=_pdf_request_headers(url),
        )
    except Exception:
        response = None

    content_type = str(getattr(response, "headers", {}).get("content-type") or "").lower()
    body = getattr(response, "content", b"") or b""
    head = body[:1024].decode("latin1", errors="ignore")
    used_browser_download = False
    used_cloudscraper = False

    if response is None or _looks_like_browser_challenge(
        status_code=int(getattr(response, "status_code", 599) or 599),
        content_type=content_type,
        head=head,
    ):
        downloaded = _download_document_bytes_via_cloudscraper(url)
        if downloaded is not None:
            used_cloudscraper = True
        else:
            downloaded = await _download_document_bytes_via_playwright(url)
        if downloaded is None:
            cf_text = await _download_text_via_cloudflare_crawl(url)
            if cf_text and len(cf_text.get("text") or "") > 100:
                extracted = str(cf_text.get("text") or "").strip()
                return SimpleNamespace(
                    url=url,
                    title=_title_from_extracted_rtf_text(text=extracted, url=url),
                    text=extracted,
                    html=cf_text.get("html") or "",
                    links=[],
                    success=True,
                    method_used="rtf_processor_cloudflare_rendering",
                    extraction_provenance={
                        "method": "rtf_processor_cloudflare_rendering",
                        "cloudflare_record_status": cf_text.get("cloudflare_record_status"),
                        "cloudflare_job_status": cf_text.get("cloudflare_job_status"),
                    },
                )
            return None
        body = downloaded.get("body") or b""
        content_type = str(downloaded.get("content_type") or "").lower()
        head = body[:1024].decode("latin1", errors="ignore")
        used_browser_download = not used_cloudscraper
    elif int(getattr(response, "status_code", 599) or 599) >= 400:
        return None

    if not body:
        return None
    if "rtf" not in content_type and not _RTF_CONTENT_PREFIX_RE.search(head):
        return None

    extracted_text = await _extract_text_from_rtf_bytes_with_processor(body, source_url=url)
    extracted_text = str(extracted_text or "").strip()
    if not extracted_text:
        return None

    return SimpleNamespace(
        url=url,
        title=_title_from_extracted_rtf_text(text=extracted_text, url=url),
        text=extracted_text,
        html="",
        links=[],
        success=True,
        method_used=(
            "rtf_processor_cloudscraper"
            if used_cloudscraper
            else "rtf_processor_playwright_download" if used_browser_download else "rtf_processor"
        ),
        extraction_provenance={
            "method": (
                "rtf_processor_cloudscraper"
                if used_cloudscraper
                else "rtf_processor_playwright_download" if used_browser_download else "rtf_processor"
            )
        },
    )


async def _scrape_maryland_comar_detail_url(url: str) -> Optional[Any]:
    parsed = urlparse(str(url or "").strip())
    if parsed.netloc.lower() != "regs.maryland.gov":
        return None
    if _MD_COMAR_DETAIL_PATH_RE.search(parsed.path or "") is None:
        return None

    try:
        response = requests.get(
            url,
            timeout=25,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        response.raise_for_status()
    except Exception:
        return None

    html = str(response.text or "")
    if not html:
        return None

    soup = BeautifulSoup(html, "html.parser")
    content_node = None
    for selector in ("main article", "main", "article", ".content"):
        content_node = soup.select_one(selector)
        if content_node is not None:
            break
    if content_node is None:
        return None

    for selector in ("nav", "header", "footer", ".breadcrumbs", ".cross-references"):
        for node in content_node.select(selector):
            node.decompose()

    extracted_text = re.sub(r"\s+", " ", content_node.get_text(" ", strip=True)).strip()
    if not extracted_text:
        return None

    title_node = soup.find("h1")
    title_text = re.sub(r"\s+", " ", title_node.get_text(" ", strip=True)).strip() if title_node else ""

    return SimpleNamespace(
        url=url,
        title=title_text or _title_from_extracted_pdf_text(text=extracted_text, url=url),
        text=extracted_text,
        html=str(content_node),
        links=[],
        success=True,
        method_used="maryland_comar_html",
        extraction_provenance={
            "method": "maryland_comar_html",
            "source_url": url,
            "content_type": str(response.headers.get("content-type") or ""),
        },
    )


def _extract_text_from_docx_bytes(docx_bytes: bytes) -> str:
    if not docx_bytes:
        return ""

    try:
        with zipfile.ZipFile(io.BytesIO(docx_bytes)) as archive:
            document_xml = archive.read("word/document.xml")
    except Exception:
        return ""

    try:
        root = ET.fromstring(document_xml)
    except Exception:
        return ""

    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    paragraphs: List[str] = []
    for paragraph in root.findall(".//w:p", namespace):
        text_parts = [str(node.text or "") for node in paragraph.findall(".//w:t", namespace)]
        paragraph_text = "".join(text_parts).strip()
        if paragraph_text:
            paragraphs.append(paragraph_text)
    return "\n\n".join(paragraphs)


async def _scrape_docx_candidate_url_with_processor(url: str) -> Optional[Any]:
    if not _is_docx_candidate_url(url):
        return None

    response = None
    try:
        response = requests.get(
            url,
            timeout=35,
            headers=_pdf_request_headers(url),
        )
    except Exception:
        response = None

    content_type = str(getattr(response, "headers", {}).get("content-type") or "").lower()
    body = getattr(response, "content", b"") or b""
    head = body[:1024].decode("latin1", errors="ignore")
    used_browser_download = False
    used_cloudscraper = False

    if response is None or _looks_like_browser_challenge(
        status_code=int(getattr(response, "status_code", 599) or 599),
        content_type=content_type,
        head=head,
    ):
        downloaded = _download_document_bytes_via_cloudscraper(url)
        if downloaded is not None:
            used_cloudscraper = True
        else:
            downloaded = await _download_document_bytes_via_playwright(url)
        if downloaded is None:
            return None
        body = downloaded.get("body") or b""
        content_type = str(downloaded.get("content_type") or "").lower()
        head = body[:1024].decode("latin1", errors="ignore")
        used_browser_download = not used_cloudscraper
    elif int(getattr(response, "status_code", 599) or 599) >= 400:
        return None

    if not body:
        return None
    if content_type.startswith("text/html") and _BAD_DISCOVERY_TEXT_RE.search(head):
        return None
    if "wordprocessingml.document" not in content_type and not body.startswith(b"PK"):
        return None

    extracted_text = _extract_text_from_docx_bytes(body).strip()
    if not extracted_text:
        return None

    method_value = (
        "docx_processor_cloudscraper"
        if used_cloudscraper
        else "docx_processor_playwright_download" if used_browser_download else "docx_processor"
    )
    return SimpleNamespace(
        url=url,
        title=_title_from_extracted_docx_text(text=extracted_text, url=url),
        text=extracted_text,
        html="",
        links=[],
        success=True,
        method_used=method_value,
        extraction_provenance={
            "method": method_value,
            "source_url": url,
            "content_type": content_type,
            "used_cloudscraper": used_cloudscraper,
            "used_browser_download": used_browser_download,
            "body_bytes": len(body),
        },
    )


def _is_substantive_rule_text(*, text: str, title: str, url: str, min_chars: int) -> bool:
    body = str(text or "").strip()
    title_value = str(title or "").strip()
    url_value = str(url or "").strip()
    parsed = urlparse(url_value)
    host = parsed.netloc.lower()
    path = parsed.path or ""
    query = parse_qs(parsed.query or "")
    official_index_page = _looks_like_official_rule_index_page(text=body, title=title_value, url=url_value)
    official_index_can_be_substantive = host == "sdlegislature.gov" and path.rstrip("/") == "/Rules/Administrative"
    tennessee_official_rule_pdf = False
    alaska_official_print_section = False
    alaska_print_section_id = ""
    alaska_print_section_cite = ""
    if host == "sharetngov.tnsosfiles.com" and path.lower().startswith("/sos/rules/") and path.lower().endswith(".pdf"):
        filename = path.rsplit("/", 1)[-1]
        chapter_id = ""
        if filename.lower().endswith(".pdf"):
            chapter_id = filename[:-4].split(".", 1)[0].strip()
        tennessee_hay = " ".join([title_value, body]).lower()
        tennessee_official_rule_pdf = (
            len(body) >= max(8000, int(min_chars))
            and bool(chapter_id)
            and re.fullmatch(r"\d{4}-\d{2}-\d{2}", chapter_id) is not None
            and ("tenncare" in tennessee_hay or "chapter" in tennessee_hay)
            and ("authority:" in tennessee_hay or "rule" in tennessee_hay or "rules" in tennessee_hay)
        )
    if host == "www.akleg.gov" and path == "/basis/aac.asp":
        media = str((query.get("media") or [""])[0]).strip().lower()
        sec_start = str((query.get("secStart") or [""])[0]).strip()
        sec_end = str((query.get("secEnd") or [""])[0]).strip()
        if media == "print" and sec_start == sec_end and _AK_AAC_SECTION_PATH_RE.fullmatch(f"/aac/{sec_start}"):
            alaska_official_print_section = True
            alaska_print_section_id = sec_start
            if "." in sec_start:
                alaska_title_num, alaska_rule_num = sec_start.split(".", 1)
                alaska_print_section_cite = f"{alaska_title_num} AAC {alaska_rule_num}"
    short_alaska_official_section = (
        alaska_official_print_section
        and len(body) >= 160
        and "repealed" not in body.lower()
        and (
            (bool(alaska_print_section_id) and alaska_print_section_id in " ".join([title_value, body]))
            or (bool(alaska_print_section_cite) and alaska_print_section_cite in " ".join([title_value, body]))
        )
    )
    arizona_official_rule_document = _looks_like_arizona_official_rule_document(
        text=body,
        title=title_value,
        url=url_value,
    )
    iowa_official_rule_document = _looks_like_iowa_official_rule_document(
        text=body,
        title=title_value,
        url=url_value,
    )
    if _looks_like_arizona_repealed_or_expired_chapter(text=body, title=title_value, url=url_value):
        return False
    if _has_disallowed_discovery_domain(url_value):
        return False
    if _NON_ADMIN_SOURCE_URL_RE.search(url_value):
        return False
    if _looks_like_binary_document_text(text=body, url=url_value):
        return False
    if _looks_like_raw_html_text(body):
        return False
    if _looks_like_new_hampshire_blocked_page(title=title_value, text=body):
        return False
    if _looks_like_forum_page(text=body, title=title_value, url=url_value):
        return False
    if _looks_like_non_rule_admin_page(text=body, title=title_value, url=url_value) and not tennessee_official_rule_pdf and not iowa_official_rule_document:
        return False
    if _looks_like_rule_inventory_page(text=body, title=title_value, url=url_value) and not official_index_can_be_substantive and not tennessee_official_rule_pdf:
        return False
    if _looks_like_shallow_montana_inventory_page(text=body, title=title_value, url=url_value):
        return False

    # Utah search and publication pages are useful discovery entrypoints, but they do not
    # represent substantive rule text. Keep them available to relaxed recovery, not to the
    # substantive corpus.
    if host in {"rules.utah.gov", "adminrules.utah.gov"} and _UT_NON_SUBSTANTIVE_INDEX_PATH_RE.search(path):
        return False

    # Indiana landing pages are useful seed inventory surfaces, but the emitted
    # corpus should prefer article/rule detail pages instead of top-level code indexes.
    if host == "iar.iga.in.gov" and path.rstrip("/") in {"/code", "/code/current", "/code/2006"}:
        return False
    if host == "iar.iga.in.gov" and path.rstrip("/") == "/iac":
        return False

    # Rhode Island notification subscription pages are operational UI, not rules.
    if host == "rules.sos.ri.gov" and path.startswith("/subscriptions/"):
        return False

    # Arizona public-services inventory pages are crawl hubs, not substantive rule text.
    if host == "apps.azsos.gov" and path.rstrip("/") in {"/public_services/Index", "/public_services/CodeTOC.htm"}:
        return False

    if host == "rules.wyo.gov" and path.lower() == "/ajaxhandler.ashx":
        handler = str((query.get("handler") or [""])[0]).strip().lower()
        wy_hay = " ".join([title_value, body])
        wy_section_hits = len(re.findall(r"\bsection\s+\d+[A-Za-z0-9.-]*\.", wy_hay, re.IGNORECASE))
        wy_statute_hits = len(re.findall(r"\bW\.?\s*S\.?\s*\d{1,2}-\d+-\d+[A-Za-z0-9.-]*\b", wy_hay, re.IGNORECASE))
        wy_min_chars = max(160, min(int(min_chars), 220))
        if (
            handler == "getruleversionhtml"
            and len(body) >= wy_min_chars
            and wy_section_hits >= 2
            and (_LEGAL_CONTENT_SIGNAL_RE.search(wy_hay) or wy_statute_hits >= 1)
        ):
            return True

    if host == "adminrules.utah.gov" and _UT_RULE_DETAIL_PATH_RE.search(path):
        if len(body) < max(120, int(min_chars)):
            return False
        if not (_RULE_BODY_SIGNAL_RE.search(" ".join([title_value, body])) or _LEGAL_CONTENT_SIGNAL_RE.search(body)):
            return False
        return True

    if len(body) < max(120, int(min_chars)):
        # PDF-based admin-rule publications often extract with sparse text; allow
        # a lower floor when URL/title still strongly indicate rule content.
        pdf_like = str(url_value).lower().endswith(".pdf") or ".pdf?" in str(url_value).lower()
        if not official_index_can_be_substantive and not (
            pdf_like
            and len(body) >= 60
            and _has_admin_signal(text=body, title=title_value, url=url_value)
            and _LEGAL_CONTENT_SIGNAL_RE.search(" ".join([title_value, body]))
        ) and not short_alaska_official_section:
            return False
    if title_value and _looks_like_placeholder_text(title_value) and not official_index_can_be_substantive and not arizona_official_rule_document and not iowa_official_rule_document:
        return False
    if _looks_like_placeholder_text(body) and not official_index_can_be_substantive and not arizona_official_rule_document and not iowa_official_rule_document and not tennessee_official_rule_pdf:
        return False
    if not _has_admin_signal(text=body, title=title_value, url=url_value) and not tennessee_official_rule_pdf:
        if not (
            arizona_official_rule_document
            and _LEGAL_CONTENT_SIGNAL_RE.search(" ".join([title_value, body]))
        ):
            return False
    if short_alaska_official_section:
        return True
    if tennessee_official_rule_pdf:
        return True
    if not official_index_can_be_substantive and not _LEGAL_CONTENT_SIGNAL_RE.search(body):
        return False
    return True


def _is_substantive_admin_statute(statute: Dict[str, Any], *, min_chars: int) -> bool:
    full_text = str(statute.get("full_text") or "")
    section_name = str(statute.get("section_name") or statute.get("short_title") or "")
    source_url = str(statute.get("source_url") or "")
    return _is_substantive_rule_text(
        text=full_text,
        title=section_name,
        url=source_url,
        min_chars=max(160, int(min_chars)),
    )


def _is_relaxed_recovery_text(*, text: str, title: str, url: str) -> bool:
    body = str(text or "").strip()
    title_value = str(title or "").strip()
    url_value = str(url or "").strip()
    official_index_page = _looks_like_official_rule_index_page(text=body, title=title_value, url=url_value)
    arizona_official_rule_document = _looks_like_arizona_official_rule_document(
        text=body,
        title=title_value,
        url=url_value,
    )
    if _has_disallowed_discovery_domain(url_value):
        return False
    if _NON_ADMIN_SOURCE_URL_RE.search(url_value):
        return False
    if _looks_like_binary_document_text(text=body, url=url_value):
        return False
    if _looks_like_raw_html_text(body):
        return False
    if _looks_like_forum_page(text=body, title=title_value, url=url_value):
        return False
    if _looks_like_non_rule_admin_page(text=body, title=title_value, url=url_value):
        return False
    if _looks_like_shallow_montana_inventory_page(text=body, title=title_value, url=url_value):
        return False
    parsed = urlparse(url_value)
    host = parsed.netloc.lower()
    path = parsed.path.rstrip("/") or "/"
    if host == "admincode.legislature.state.al.us" and path == "/administrative-code":
        if not _AL_RULE_NUMBER_RE.fullmatch(_alabama_public_code_number_from_url(url_value)):
            return False
    if host == "apps.azsos.gov" and path in {"/public_services/CodeTOC.htm", "/public_services/Index"}:
        return False
    if host == "iar.iga.in.gov" and path == "/iac":
        return False
    if host == "rules.sos.ri.gov" and path.startswith("/subscriptions"):
        return False
    if title_value and _looks_like_placeholder_text(title_value) and not official_index_page and not arizona_official_rule_document:
        return False
    if body and _looks_like_placeholder_text(body) and not official_index_page and not arizona_official_rule_document:
        return False
    if official_index_page and len(body) >= 120 and _has_admin_signal(text=body, title=title_value, url=url_value):
        return True
    if len(body) >= 80 and _has_admin_signal(text=body, title=title_value, url=url_value) and _LEGAL_CONTENT_SIGNAL_RE.search(body):
        return True
    return False


def _should_emit_relaxed_recovery_statute(*, text: str, title: str, url: str) -> bool:
    body = str(text or "").strip()
    title_value = str(title or "").strip()
    url_value = str(url or "").strip()
    arizona_official_rule_document = _looks_like_arizona_official_rule_document(
        text=body,
        title=title_value,
        url=url_value,
    )

    if title_value and _looks_like_placeholder_text(title_value) and not arizona_official_rule_document:
        return False
    if body and _looks_like_placeholder_text(body) and not arizona_official_rule_document:
        return False
    if _looks_like_non_rule_admin_page(text=body, title=title_value, url=url_value):
        return False
    if _looks_like_arizona_repealed_or_expired_chapter(text=body, title=title_value, url=url_value):
        return False
    if _looks_like_rule_inventory_page(text=body, title=title_value, url=url_value):
        return False
    if _looks_like_official_rule_index_page(text=body, title=title_value, url=url_value):
        return False

    return True


def _candidate_links_from_scrape(
    scraped: Any,
    base_host: str,
    page_url: str = "",
    limit: int = 10,
    allowed_hosts: Optional[set[str]] = None,
) -> List[str]:
    ranked: List[tuple[int, str, str]] = []
    seen = set()
    for item in list(getattr(scraped, "links", []) or []):
        if not isinstance(item, dict):
            continue
        link_url = str(item.get("url") or "").strip()
        link_text = str(item.get("text") or "").strip()
        if link_url and not link_url.startswith(("http://", "https://")) and page_url:
            link_url = urljoin(page_url, link_url)
        if not link_url.startswith(("http://", "https://")):
            continue
        host = urlparse(link_url).netloc
        if allowed_hosts:
            if host and not _host_matches_allowed(host, allowed_hosts):
                continue
        elif base_host and host and host != base_host:
            continue
        if not _ADMIN_LINK_HINT_RE.search(" ".join([link_url, link_text])):
            continue
        key = link_url.lower()
        if key in seen:
            continue
        seen.add(key)
        score = _score_candidate_link(link_url, link_text, page_url)
        if score <= 0:
            continue
        ranked.append((score, link_url, link_text))
    ranked = _filter_california_westlaw_links_for_depth(ranked, page_url=page_url)
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [link_url for _, link_url, _ in ranked[: max(1, int(limit))]]


def _candidate_arizona_rule_urls_from_text(*, text: str, page_url: str = "", limit: int = 12) -> List[str]:
    body = unescape(str(text or ""))
    if not body:
        return []

    page_host = urlparse(str(page_url or "").strip()).netloc.lower()
    if page_host not in {"apps.azsos.gov", "azsos.gov", "www.azsos.gov"} and "apps.azsos.gov" not in body.lower():
        return []

    out: List[str] = []
    seen = set()
    pattern = re.compile(
        r"(?:https?://apps\.azsos\.gov)?(?P<path>/?public_services/Title_\d{2}/\d+-\d+\.(?:pdf|rtf))",
        re.IGNORECASE,
    )
    for match in pattern.finditer(body):
        path = str(match.group("path") or "").strip()
        if not path:
            continue
        if not path.startswith("/"):
            path = f"/{path}"
        candidate_url = urljoin("https://apps.azsos.gov", path)
        key = _url_key(candidate_url)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(candidate_url)
        if len(out) >= max(1, int(limit)):
            break
    return out


async def _discover_arizona_rule_document_urls(
    *,
    seed_urls: List[str],
    live_scraper: Optional[Any] = None,
    live_fetch_api: Optional[Any] = None,
    direct_fetch_api: Optional[Any] = None,
    limit: int = 8,
) -> List[str]:
    relevant_seed_urls = [
        str(url or "").strip()
        for url in list(seed_urls or [])
        if urlparse(str(url or "").strip()).netloc.lower() in {"apps.azsos.gov", "azsos.gov", "www.azsos.gov"}
    ]
    if not relevant_seed_urls:
        return []

    limit_n = max(1, int(limit))
    discovered_candidates: List[tuple[str, int]] = []
    seen_documents: set[str] = set()
    seen_pages: set[str] = set()
    frontier: List[str] = [
        "https://apps.azsos.gov/public_services/CodeTOC.htm",
        "https://apps.azsos.gov/public_services/Index/",
    ]
    for seed_url in relevant_seed_urls:
        if seed_url not in frontier:
            frontier.append(seed_url)

    async def _extract_from_page(page_url: str) -> None:
        page_key = _url_key(page_url)
        if not page_key or page_key in seen_pages:
            return
        seen_pages.add(page_key)

        extracted_sources: List[str] = []
        if live_scraper is not None:
            try:
                scraped = await asyncio.wait_for(live_scraper.scrape(page_url), timeout=20.0)
                scraped_html = str(getattr(scraped, "html", "") or "")
                scraped_text = str(getattr(scraped, "text", "") or "")
                if scraped_html or scraped_text:
                    extracted_sources.append(scraped_html or scraped_text)
            except Exception:
                pass

        if not extracted_sources:
            page_host = urlparse(page_url).netloc
            fetch_api = live_fetch_api if _prefers_live_fetch(page_url) else direct_fetch_api
            if fetch_api is not None:
                try:
                    fetched = await asyncio.wait_for(
                        _run_blocking_fetch(
                            fetch_api.fetch,
                            UnifiedFetchRequest(
                                url=page_url,
                                timeout_seconds=25,
                                mode=OperationMode.BALANCED,
                                domain=".gov" if page_host.endswith(".gov") else "legal",
                            ),
                        ),
                        timeout=20.0,
                    )
                    fetched_doc = getattr(fetched, "document", None)
                    fetched_html = str(getattr(fetched_doc, "html", "") or "")
                    fetched_text = str(getattr(fetched_doc, "text", "") or "")
                    if fetched_html or fetched_text:
                        extracted_sources.append(fetched_html or fetched_text)
                except Exception:
                    pass

        if not extracted_sources:
            headers = {
                "User-Agent": "Mozilla/5.0",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }

            def _fetch_via_requests() -> str:
                session = requests.Session()
                try:
                    response = session.get(page_url, timeout=15, headers=headers)
                    response.raise_for_status()
                    return str(response.text or "")
                except Exception:
                    return ""
                finally:
                    session.close()

            response_text = await asyncio.to_thread(_fetch_via_requests)
            if response_text:
                extracted_sources.append(response_text)

        for source_text in extracted_sources:
            for candidate_url in _candidate_arizona_rule_urls_from_text(
                text=source_text,
                page_url=page_url,
                limit=max(limit_n * 8, 48),
            ):
                document_key = _url_key(candidate_url)
                if not document_key or document_key in seen_documents:
                    continue
                seen_documents.add(document_key)
                discovered_candidates.append((candidate_url, _score_candidate_url(candidate_url)))

    for page_url in frontier[:4]:
        await _extract_from_page(page_url)
        if len(discovered_candidates) >= max(limit_n * 2, 8):
            break

    return _prioritized_direct_detail_urls_from_candidates(
        discovered_candidates,
        limit=limit_n,
    )


def _candidate_vermont_rule_urls_from_html(*, html: str, page_url: str = "", limit: int = 12) -> List[str]:
    body = str(html or "")
    if not body:
        return []

    parsed_page = urlparse(str(page_url or "").strip())
    host = parsed_page.netloc.lower()
    path = (parsed_page.path or "").lower()

    out: List[str] = []
    seen: set[str] = set()
    limit_n = max(1, int(limit))

    if host in {"lexisnexis.com", "www.lexisnexis.com", "advance.lexis.com"}:
        for doc_path in re.findall(r'data-docfullpath=["\']([^"\']+)["\']', body, re.IGNORECASE):
            normalized_path = str(doc_path or "").strip()
            if not normalized_path:
                continue
            candidate_url = urljoin("https://advance.lexis.com", normalized_path)
            if not _VT_LEXIS_DOC_PATH_RE.fullmatch(urlparse(candidate_url).path or ""):
                continue
            key = _url_key(candidate_url)
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(candidate_url)
            if len(out) >= limit_n:
                return out
    return out


def _candidate_massachusetts_cmr_urls_from_html(
    *,
    html: str,
    page_url: str,
    limit: int = 20,
    include_inventory: bool = True,
) -> List[str]:
    body = str(html or "")
    if not body:
        return []

    limit_n = max(1, int(limit))
    ranked: List[tuple[int, str, str]] = []
    seen: set[str] = set()
    for href, anchor_body in re.findall(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', body, re.IGNORECASE | re.DOTALL):
        link_url = unescape(str(href or "").strip())
        link_text = re.sub(r"<[^>]+>", " ", str(anchor_body or ""))
        link_text = re.sub(r"\s+", " ", link_text).strip()
        if link_url and not link_url.startswith(("http://", "https://")):
            link_url = urljoin(page_url, link_url)
        if not link_url.startswith(("http://", "https://")):
            continue

        parsed = urlparse(link_url)
        host = parsed.netloc.lower()
        if host not in {"www.mass.gov", "mass.gov"}:
            continue

        path = parsed.path or ""
        is_detail = bool(_MA_CMR_DETAIL_PATH_RE.search(path))
        is_inventory = bool(_MA_CMR_INVENTORY_PATH_RE.search(path))
        if _MA_GENERAL_LAWS_PATH_RE.search(path):
            continue
        if not is_detail and not is_inventory:
            continue
        if not include_inventory and not is_detail:
            continue

        key = _url_key(link_url)
        if not key or key in seen:
            continue
        seen.add(key)

        score = _score_candidate_link(link_url, link_text, page_url)
        if is_detail:
            score += 4
        elif path.lower().startswith("/law-library/"):
            score += 2
        if score <= 0:
            continue
        ranked.append((score, link_url, link_text))

    ranked.sort(key=lambda item: item[0], reverse=True)
    return [link_url for _, link_url, _ in ranked[:limit_n]]


async def _discover_massachusetts_cmr_document_urls(
    *,
    seed_urls: List[str],
    live_scraper: Any,
    live_fetch_api: Any,
    direct_fetch_api: Any,
    allowed_hosts: set[str],
    limit: int = 12,
) -> List[str]:
    frontier: List[str] = [
        url
        for url in seed_urls
        if urlparse(str(url or "").strip()).netloc.lower() in {"www.mass.gov", "mass.gov"}
        and _MA_CMR_INVENTORY_PATH_RE.search(urlparse(str(url or "").strip()).path or "")
    ]
    if not frontier:
        return []

    document_urls: List[str] = []
    seen_pages: set[str] = set()
    seen_inventory: set[str] = {_url_key(url) for url in frontier if _url_key(url)}
    seen_documents: set[str] = set()

    for _depth in range(3):
        next_frontier: List[str] = []
        for page_url in frontier[:4]:
            page_key = _url_key(page_url)
            if not page_key or page_key in seen_pages:
                continue
            seen_pages.add(page_key)

            html = ""
            scraped = None
            try:
                scraped = await asyncio.wait_for(live_scraper.scrape(page_url), timeout=12.0)
                html = str(getattr(scraped, "html", "") or "")
            except Exception:
                scraped = None

            if not html:
                page_host = urlparse(page_url).netloc
                fetch_api = live_fetch_api if _prefers_live_fetch(page_url) else direct_fetch_api
                try:
                    fetched = await asyncio.wait_for(
                        _run_blocking_fetch(
                            fetch_api.fetch,
                            UnifiedFetchRequest(
                                url=page_url,
                                timeout_seconds=25,
                                mode=OperationMode.BALANCED,
                                domain=".gov" if page_host.endswith(".gov") else "legal",
                            ),
                        ),
                        timeout=12.0,
                    )
                    fetched_doc = getattr(fetched, "document", None)
                    html = str(getattr(fetched_doc, "html", "") or "")
                except Exception:
                    html = ""

            if not html:
                continue

            links = _candidate_massachusetts_cmr_urls_from_html(
                html=html,
                page_url=page_url,
                limit=max(limit * 4, 24),
                include_inventory=True,
            )
            for link_url in links:
                parsed_link = urlparse(link_url)
                host = parsed_link.netloc
                if allowed_hosts and host and not _host_matches_allowed(host, allowed_hosts):
                    continue

                path = parsed_link.path or ""
                link_key = _url_key(link_url)
                if _MA_CMR_DETAIL_PATH_RE.search(path):
                    if link_key and link_key not in seen_documents:
                        seen_documents.add(link_key)
                        document_urls.append(link_url)
                elif _MA_CMR_INVENTORY_PATH_RE.search(path):
                    if link_key and link_key not in seen_inventory:
                        seen_inventory.add(link_key)
                        next_frontier.append(link_url)

                if len(document_urls) >= max(1, int(limit)):
                    return document_urls[: max(1, int(limit))]

        if not next_frontier:
            break
        frontier = next_frontier

    return document_urls[: max(1, int(limit))]


def _candidate_texas_rule_urls_from_html(*, html: str, page_url: str = "", limit: int = 12) -> List[str]:
    body = str(html or "")
    if not body:
        return []

    parsed_page = urlparse(str(page_url or "").strip())
    host = parsed_page.netloc.lower()
    path = (parsed_page.path or "").lower()
    if host != "texas-sos.appianportalsgov.com" or path != "/rules-and-meetings":
        return []

    out: List[str] = []
    seen: set[str] = set()
    limit_n = max(1, int(limit))
    for href in re.findall(r'<a\b[^>]*href=["\']([^"\']+)["\']', body, re.IGNORECASE):
        candidate_url = unescape(str(href or "").strip())
        if candidate_url and not candidate_url.startswith(("http://", "https://")) and page_url:
            candidate_url = urljoin(page_url, candidate_url)
        if not candidate_url.startswith(("http://", "https://")):
            continue
        parsed_candidate = urlparse(candidate_url)
        if parsed_candidate.netloc.lower() != "texas-sos.appianportalsgov.com":
            continue
        if (parsed_candidate.path or "").lower() != "/rules-and-meetings":
            continue
        query_params = parse_qs(parsed_candidate.query or "")
        interface = str((query_params.get("interface") or [""])[0]).strip().upper()
        if interface == "VIEW_TAC_SUMMARY":
            record_id = str((query_params.get("recordId") or [""])[0]).strip()
            if not record_id.isdigit():
                continue
        elif interface == "VIEW_TAC":
            if not any(str((query_params.get(key) or [""])[0]).strip() for key in ("title", "part", "chapter", "subchapter")):
                continue
        else:
            continue
        key = _url_key(candidate_url)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(candidate_url)
        if len(out) >= limit_n:
            break
    return out


def _candidate_wyoming_rule_urls_from_html(*, html: str, page_url: str = "", limit: int = 12) -> List[str]:
    body = str(html or "")
    if not body:
        return []

    parsed_page = urlparse(str(page_url or "").strip())
    host = parsed_page.netloc.lower()
    path = (parsed_page.path or "").lower()
    query = parse_qs(parsed_page.query or "")
    if host != "rules.wyo.gov":
        return []

    out: List[str] = []
    seen: set[str] = set()
    limit_n = max(1, int(limit))

    for match in re.finditer(
        r'<a\b[^>]*class=["\'][^"\']*\bsearch-rule-link\b[^"\']*["\'][^>]*data-whatever=["\']([1-9]\d*)["\']',
        body,
        re.IGNORECASE,
    ):
        rule_id = str(match.group(1) or "").strip()
        if not rule_id:
            continue
        candidate_url = f"https://rules.wyo.gov/AjaxHandler.ashx?handler=GetRuleVersionHTML&RULE_VERSION_ID={rule_id}"
        key = _url_key(candidate_url)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(candidate_url)
        if len(out) >= limit_n:
            return out

    if path in {"/search.aspx", "/agencies.aspx"} or (
        path == "/ajaxhandler.ashx" and str((query.get("handler") or [""])[0]).strip().lower() == "search"
    ):
        for match in re.finditer(
            r'<span\b[^>]*class=["\'][^"\']*\bprogram_id\b[^"\']*["\'][^>]*>\s*(\d+)\s*</span>',
            body,
            re.IGNORECASE,
        ):
            program_id = str(match.group(1) or "").strip()
            if not program_id:
                continue
            candidate_url = (
                "https://rules.wyo.gov/AjaxHandler.ashx?handler=Search_GetProgramRules"
                f"&PROGRAM_ID={program_id}&MODE=7"
            )
            key = _url_key(candidate_url)
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(candidate_url)
            if len(out) >= limit_n:
                break

    return out


async def _discover_wyoming_rule_document_urls(*, seed_urls: List[str], limit: int = 8) -> List[str]:
    relevant_seed_urls = [
        url
        for url in seed_urls
        if urlparse(str(url or "").strip()).netloc.lower() == "rules.wyo.gov"
    ]
    if not relevant_seed_urls:
        return []

    limit_n = max(1, int(limit or 1))
    session = requests.Session()
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    discovered_urls: List[str] = []
    seen_keys: set[str] = set()
    seen_program_keys: set[str] = set()

    def _record(candidate_url: str) -> bool:
        candidate_key = _url_key(candidate_url)
        if not candidate_key or candidate_key in seen_keys:
            return False
        seen_keys.add(candidate_key)
        discovered_urls.append(candidate_url)
        return len(discovered_urls) >= limit_n

    for seed_url in relevant_seed_urls[:6]:
        try:
            seed_response = await asyncio.to_thread(
                session.get,
                seed_url,
                timeout=25,
                headers=headers,
            )
            seed_response.raise_for_status()
        except Exception:
            continue

        program_urls = _candidate_wyoming_rule_urls_from_html(
            html=seed_response.text,
            page_url=seed_url,
            limit=max(12, limit_n * 4),
        )
        for program_url in program_urls:
            program_key = _url_key(program_url)
            if not program_key or program_key in seen_program_keys:
                continue
            seen_program_keys.add(program_key)
            program_scraped = await _scrape_wyoming_rule_detail_via_ajax(program_url)
            if program_scraped is None:
                continue
            program_html = str(getattr(program_scraped, "html", "") or "")
            viewer_urls = _candidate_wyoming_rule_urls_from_html(
                html=program_html,
                page_url=program_url,
                limit=max(12, limit_n * 4),
            )
            for viewer_url in viewer_urls:
                if _record(viewer_url):
                    return discovered_urls

    return discovered_urls


def _candidate_links_from_html(
    html: str,
    base_host: str,
    page_url: str = "",
    limit: int = 10,
    allowed_hosts: Optional[set[str]] = None,
) -> List[str]:
    body = str(html or "")
    if not body:
        return []
    ranked: List[tuple[int, str, str]] = []
    seen = set()
    for href, anchor_body in re.findall(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', body, re.IGNORECASE | re.DOTALL):
        link_url = unescape(str(href or "").strip())
        link_text = re.sub(r"<[^>]+>", " ", str(anchor_body or ""))
        link_text = re.sub(r"\s+", " ", link_text).strip()
        if link_url and not link_url.startswith(("http://", "https://")) and page_url:
            link_url = urljoin(page_url, link_url)
        if not link_url.startswith(("http://", "https://")):
            continue
        host = urlparse(link_url).netloc
        if allowed_hosts:
            if host and not _host_matches_allowed(host, allowed_hosts):
                continue
        elif base_host and host and host != base_host:
            continue
        if not _ADMIN_LINK_HINT_RE.search(" ".join([link_url, link_text])):
            continue
        key = link_url.lower()
        if key in seen:
            continue
        seen.add(key)
        score = _score_candidate_link(link_url, link_text, page_url)
        if score <= 0:
            continue
        ranked.append((score, link_url, link_text))
    for link_url in _candidate_arizona_rule_urls_from_text(text=body, page_url=page_url, limit=limit):
        host = urlparse(link_url).netloc
        if allowed_hosts:
            if host and not _host_matches_allowed(host, allowed_hosts):
                continue
        elif base_host and host and host != base_host:
            continue
        key = link_url.lower()
        if key in seen:
            continue
        seen.add(key)
        score = _score_candidate_link(link_url, "", page_url)
        if score <= 0:
            continue
        ranked.append((score, link_url, ""))
    for link_url in _candidate_texas_rule_urls_from_html(html=body, page_url=page_url, limit=limit):
        host = urlparse(link_url).netloc
        if allowed_hosts:
            if host and not _host_matches_allowed(host, allowed_hosts):
                continue
        elif base_host and host and host != base_host:
            continue
        key = link_url.lower()
        if key in seen:
            continue
        seen.add(key)
        score = _score_candidate_link(link_url, "", page_url)
        if score <= 0:
            continue
        ranked.append((score, link_url, ""))
    for link_url in _candidate_vermont_rule_urls_from_html(html=body, page_url=page_url, limit=limit):
        host = urlparse(link_url).netloc
        if allowed_hosts:
            if host and not _host_matches_allowed(host, allowed_hosts):
                continue
        elif base_host and host and host != base_host:
            continue
        key = link_url.lower()
        if key in seen:
            continue
        seen.add(key)
        score = _score_candidate_link(link_url, "", page_url)
        if score <= 0:
            continue
        ranked.append((score, link_url, ""))
    for link_url in _candidate_wyoming_rule_urls_from_html(html=body, page_url=page_url, limit=limit):
        host = urlparse(link_url).netloc
        if allowed_hosts:
            if host and not _host_matches_allowed(host, allowed_hosts):
                continue
        elif base_host and host and host != base_host:
            continue
        key = link_url.lower()
        if key in seen:
            continue
        seen.add(key)
        score = _score_candidate_link(link_url, "", page_url)
        if score <= 0:
            continue
        ranked.append((score, link_url, ""))
    for link_url in _candidate_arkansas_rule_urls_from_html(html=body, page_url=page_url, limit=limit):
        host = urlparse(link_url).netloc
        if allowed_hosts:
            if host and not _host_matches_allowed(host, allowed_hosts):
                continue
        elif base_host and host and host != base_host:
            continue
        key = link_url.lower()
        if key in seen:
            continue
        seen.add(key)
        score = _score_candidate_link(link_url, "", page_url)
        if score <= 0:
            continue
        ranked.append((score, link_url, ""))
    for link_url in _candidate_oklahoma_rule_urls_from_text(text=body, page_url=page_url, limit=limit):
        host = urlparse(link_url).netloc
        if allowed_hosts:
            if host and not _host_matches_allowed(host, allowed_hosts):
                continue
        elif base_host and host and host != base_host:
            continue
        key = link_url.lower()
        if key in seen:
            continue
        seen.add(key)
        score = _score_candidate_link(link_url, "", page_url)
        if score <= 0:
            continue
        ranked.append((score, link_url, ""))
    ranked = _filter_california_westlaw_links_for_depth(ranked, page_url=page_url)
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [link_url for _, link_url, _ in ranked[: max(1, int(limit))]]


def _filter_california_westlaw_links_for_depth(
    ranked_links: List[tuple[int, str, str]],
    *,
    page_url: str,
) -> List[tuple[int, str, str]]:
    page_parts = urlparse(str(page_url or "").strip())
    if page_parts.netloc.lower() != "govt.westlaw.com":
        return ranked_links
    if not page_parts.path.lower().startswith("/calregs/browse/home/california/californiacodeofregulations"):
        return ranked_links

    document_links = [
        item for item in ranked_links if urlparse(item[1]).path.lower().startswith("/calregs/document/")
    ]
    if document_links:
        return document_links

    for pattern in (r"\barticle\b", r"\bchapter\b", r"\bdivision\b", r"\btitle\b"):
        filtered = [item for item in ranked_links if re.search(pattern, item[2], re.IGNORECASE)]
        if filtered:
            return filtered

    return ranked_links


def _georgia_bootstrap_priority(url: str) -> int:
    value = str(url or "").strip()
    parsed = urlparse(value)
    path = parsed.path or ""
    score = _score_candidate_url(value)
    if _GA_GAC_RULE_PATH_RE.fullmatch(path):
        return score + 100
    if _GA_GAC_SUBJECT_PATH_RE.fullmatch(path):
        return score + 80
    if _GA_GAC_CHAPTER_PATH_RE.fullmatch(path):
        return score + 60
    if _GA_GAC_DEPARTMENT_PATH_RE.fullmatch(path):
        return score + 40
    if path.rstrip("/").lower() == "/gac":
        return score + 20
    return score


def _normalize_connecticut_eregulations_url(url: str) -> str:
    value = str(url or "").strip()
    parsed = urlparse(value)
    if parsed.netloc.lower() != "eregulations.ct.gov":
        return value
    return urlunparse(("https", parsed.netloc, parsed.path, parsed.params, parsed.query, parsed.fragment))


def _connecticut_bootstrap_priority(url: str) -> int:
    value = _normalize_connecticut_eregulations_url(url)
    parsed = urlparse(value)
    path = parsed.path or ""
    score = _score_candidate_url(value)
    if _CT_EREGS_SECTION_PATH_RE.fullmatch(path):
        return score + 100
    if _CT_EREGS_SUBTITLE_PATH_RE.fullmatch(path):
        return score + 70
    if _CT_EREGS_TITLE_PATH_RE.fullmatch(path):
        return score + 50
    if _CT_EREGS_ROOT_PATH_RE.fullmatch(path):
        return score + 20
    return score


def _colorado_pdf_url(base_url: str, rule_version_id: str, file_name: str) -> str:
    parsed = urlparse(base_url)
    host = parsed.netloc or "www.coloradosos.gov"
    encoded_name = quote(file_name, safe="")
    return (
        f"https://{host}/CCR/{encoded_name}.pdf?ruleVersionId={rule_version_id}"
        f"&fileName={encoded_name}"
    )


def _colorado_latest_pdf_urls_from_html(*, html: str, base_url: str) -> List[str]:
    latest_by_name: Dict[str, tuple[int, str]] = {}
    for match in _CO_CCR_OPEN_RULE_WINDOW_RE.finditer(str(html or "")):
        rule_version_id = str(match.group("rule_version_id") or "").strip()
        file_name = str(match.group("file_name") or "").strip()
        if not rule_version_id.isdigit() or not file_name:
            continue
        version_num = int(rule_version_id)
        current = latest_by_name.get(file_name)
        if current is not None and current[0] >= version_num:
            continue
        latest_by_name[file_name] = (
            version_num,
            _colorado_pdf_url(base_url, rule_version_id, file_name),
        )
    return [url for _, url in sorted(latest_by_name.values(), key=lambda item: item[0], reverse=True)]


async def _discover_connecticut_rule_document_urls(
    *,
    seed_urls: List[str],
    live_scraper: Any,
    allowed_hosts: set[str],
    limit: int = 8,
) -> List[str]:
    discovered_urls: List[str] = []
    seen_page_keys: set[str] = set()
    seen_document_keys: set[str] = set()

    def _record(url: str) -> bool:
        normalized_url = _normalize_connecticut_eregulations_url(url)
        key = _url_key(normalized_url)
        if not key or key in seen_document_keys:
            return False
        seen_document_keys.add(key)
        discovered_urls.append(normalized_url)
        return len(discovered_urls) >= max(1, int(limit))

    def _dedupe(values: List[str]) -> List[str]:
        deduped: List[str] = []
        seen_keys: set[str] = set()
        for value in values:
            normalized_value = _normalize_connecticut_eregulations_url(value)
            key = _url_key(normalized_value)
            if not key or key in seen_keys:
                continue
            seen_keys.add(key)
            deduped.append(normalized_value)
        return deduped

    async def _fetch_links(page_url: str, *, limit_n: int) -> List[str]:
        normalized_page_url = _normalize_connecticut_eregulations_url(page_url)
        page_key = _url_key(normalized_page_url)
        if not page_key or page_key in seen_page_keys:
            return []
        seen_page_keys.add(page_key)

        try:
            scraped = await asyncio.wait_for(live_scraper.scrape(normalized_page_url), timeout=10.0)
        except Exception:
            return []

        candidate_links = _candidate_links_from_scrape(
            scraped,
            base_host="eregulations.ct.gov",
            page_url=normalized_page_url,
            limit=max(8, int(limit_n) * 3),
            allowed_hosts=allowed_hosts,
        )
        html = str(getattr(scraped, "html", "") or "")
        if html:
            candidate_links.extend(
                _candidate_links_from_html(
                    html,
                    base_host="eregulations.ct.gov",
                    page_url=normalized_page_url,
                    limit=max(8, int(limit_n) * 3),
                    allowed_hosts=allowed_hosts,
                )
            )
        candidate_links = _dedupe(candidate_links)
        candidate_links.sort(key=_connecticut_bootstrap_priority, reverse=True)
        return candidate_links[: max(1, int(limit_n))]

    root_url = "https://eregulations.ct.gov/eRegsPortal/Browse/RCSA"
    for seed_url in seed_urls:
        seed_value = _normalize_connecticut_eregulations_url(seed_url)
        parsed = urlparse(seed_value)
        if parsed.netloc.lower() == "eregulations.ct.gov" and _CT_EREGS_ROOT_PATH_RE.fullmatch(parsed.path or ""):
            root_url = seed_value.rstrip("/")
            break

    title_urls = [
        link_url
        for link_url in await _fetch_links(root_url, limit_n=max(10, min(max(1, int(limit)) * 3, 18)))
        if _CT_EREGS_TITLE_PATH_RE.fullmatch(urlparse(link_url).path or "")
    ][:10]

    subtitle_urls: List[str] = []
    for title_url in title_urls:
        subtitle_urls.extend(
            link_url
            for link_url in await _fetch_links(title_url, limit_n=max(8, min(max(1, int(limit)) * 3, 24)))
            if _CT_EREGS_SUBTITLE_PATH_RE.fullmatch(urlparse(link_url).path or "")
        )
        if len(subtitle_urls) >= max(12, min(max(1, int(limit)) * 4, 24)):
            break
    subtitle_urls = _dedupe(subtitle_urls)[: max(12, min(max(1, int(limit)) * 4, 24))]

    for subtitle_url in subtitle_urls:
        for link_url in await _fetch_links(subtitle_url, limit_n=max(8, min(max(1, int(limit)) * 4, 24))):
            if _CT_EREGS_SECTION_PATH_RE.fullmatch(urlparse(link_url).path or ""):
                if _record(link_url):
                    return discovered_urls

    return discovered_urls


async def _discover_colorado_rule_document_urls(
    *,
    seed_urls: List[str],
    live_scraper: Any,
    allowed_hosts: set[str],
    limit: int = 8,
) -> List[str]:
    discovered_urls: List[str] = []
    seen_page_keys: set[str] = set()
    seen_document_keys: set[str] = set()

    def _record(url: str) -> bool:
        key = _url_key(url)
        if not key or key in seen_document_keys:
            return False
        seen_document_keys.add(key)
        discovered_urls.append(url)
        return len(discovered_urls) >= max(1, int(limit))

    def _dedupe(values: List[str]) -> List[str]:
        deduped: List[str] = []
        seen_keys: set[str] = set()
        for value in values:
            key = _url_key(value)
            if not key or key in seen_keys:
                continue
            seen_keys.add(key)
            deduped.append(value)
        return deduped

    def _is_colorado_seed_or_inventory_url(url: str) -> bool:
        parsed = urlparse(str(url or "").strip())
        host = parsed.netloc.lower()
        path = parsed.path or ""
        return host in {"www.sos.state.co.us", "www.coloradosos.gov"} and any(
            pattern.fullmatch(path)
            for pattern in (
                _CO_CCR_WELCOME_PATH_RE,
                _CO_CCR_DEPT_LIST_PATH_RE,
                _CO_CCR_AGENCY_LIST_PATH_RE,
                _CO_CCR_DOC_LIST_PATH_RE,
            )
        )

    def _colorado_links_from_scraped(scraped: Any, page_url: str) -> List[str]:
        candidate_links: List[str] = []
        candidate_links.extend(
            _candidate_links_from_scrape(
                scraped,
                base_host=urlparse(page_url).netloc,
                page_url=page_url,
                limit=64,
                allowed_hosts=allowed_hosts,
            )
        )
        html = str(getattr(scraped, "html", "") or "")
        if html:
            candidate_links.extend(
                _candidate_links_from_html(
                    html,
                    base_host=urlparse(page_url).netloc,
                    page_url=page_url,
                    limit=64,
                    allowed_hosts=allowed_hosts,
                )
            )
        return _dedupe(candidate_links)

    async def _scrape(url: str) -> Any:
        page_key = _url_key(url)
        if not page_key or page_key in seen_page_keys:
            return None
        seen_page_keys.add(page_key)
        try:
            scraped = await asyncio.wait_for(live_scraper.scrape(url), timeout=10.0)
            scraped_html = str(getattr(scraped, "html", "") or "")
            if scraped_html.strip():
                return scraped
        except Exception:
            scraped = None

        def _fallback_fetch() -> Any:
            response = requests.get(
                url,
                timeout=15,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            response.raise_for_status()
            html = response.text or ""
            soup = BeautifulSoup(html, "html.parser")
            title = ""
            if soup.title and soup.title.string:
                title = str(soup.title.string).strip()
            text = soup.get_text(" ", strip=True)
            return SimpleNamespace(html=html, text=text, title=title)

        try:
            return await asyncio.wait_for(asyncio.to_thread(_fallback_fetch), timeout=20.0)
        except Exception:
            return None

    async def _fetch_html_direct(url: str) -> str:
        def _run() -> str:
            response = requests.get(
                url,
                timeout=20,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            response.raise_for_status()
            return str(response.text or "")

        try:
            return await asyncio.wait_for(asyncio.to_thread(_run), timeout=25.0)
        except Exception:
            return ""

    inventory_urls = [url for url in seed_urls if _is_colorado_seed_or_inventory_url(url)]
    doc_list_urls = [url for url in inventory_urls if _CO_CCR_DOC_LIST_PATH_RE.fullmatch(urlparse(url).path or "")]
    agency_urls = [url for url in inventory_urls if _CO_CCR_AGENCY_LIST_PATH_RE.fullmatch(urlparse(url).path or "")]
    dept_urls = [url for url in inventory_urls if _CO_CCR_DEPT_LIST_PATH_RE.fullmatch(urlparse(url).path or "")]

    for doc_list_url in _dedupe(doc_list_urls)[:4]:
        doc_list_html = await _fetch_html_direct(doc_list_url)
        if not doc_list_html:
            continue
        display_rule_urls: List[str] = []
        for rule_id in re.findall(r"DisplayRule\.do\?action=ruleinfo(?:&amp;|&)ruleId=(\d+)", doc_list_html, re.IGNORECASE):
            display_rule_urls.append(urljoin(doc_list_url, f"DisplayRule.do?action=ruleinfo&ruleId={rule_id}"))
        for display_rule_url in _dedupe(display_rule_urls)[: max(8, int(limit) * 4)]:
            html = await _fetch_html_direct(display_rule_url)
            if not html:
                continue
            for pdf_url in _colorado_latest_pdf_urls_from_html(html=html, base_url=display_rule_url):
                if _record(pdf_url):
                    return discovered_urls

    if discovered_urls:
        return discovered_urls

    if not doc_list_urls:
        for dept_url in dept_urls[:2]:
            scraped = await _scrape(dept_url)
            if scraped is None:
                continue
            for link_url in _colorado_links_from_scraped(scraped, dept_url):
                if _CO_CCR_DOC_LIST_PATH_RE.fullmatch(urlparse(link_url).path or ""):
                    doc_list_urls.append(link_url)
                elif _CO_CCR_AGENCY_LIST_PATH_RE.fullmatch(urlparse(link_url).path or ""):
                    agency_urls.append(link_url)
            if doc_list_urls:
                break

    if not doc_list_urls:
        for agency_url in _dedupe(agency_urls)[:4]:
            scraped = await _scrape(agency_url)
            if scraped is None:
                continue
            for link_url in _colorado_links_from_scraped(scraped, agency_url):
                if _CO_CCR_DOC_LIST_PATH_RE.fullmatch(urlparse(link_url).path or ""):
                    doc_list_urls.append(link_url)
            if len(doc_list_urls) >= 4:
                break

    display_rule_urls: List[str] = []
    for doc_list_url in _dedupe(doc_list_urls)[:4]:
        scraped = await _scrape(doc_list_url)
        if scraped is None:
            continue
        doc_list_html = str(getattr(scraped, "html", "") or "")
        for rule_id in re.findall(r"DisplayRule\.do\?action=ruleinfo&amp;ruleId=(\d+)", doc_list_html, re.IGNORECASE):
            display_rule_urls.append(urljoin(doc_list_url, f"DisplayRule.do?action=ruleinfo&ruleId={rule_id}"))
        for rule_id in re.findall(r"DisplayRule\.do\?action=ruleinfo&ruleId=(\d+)", doc_list_html, re.IGNORECASE):
            display_rule_urls.append(urljoin(doc_list_url, f"DisplayRule.do?action=ruleinfo&ruleId={rule_id}"))
        for link_url in _colorado_links_from_scraped(scraped, doc_list_url):
            parsed = urlparse(link_url)
            query_params = parse_qs(parsed.query or "")
            if _CO_CCR_DISPLAY_RULE_PATH_RE.fullmatch(parsed.path or ""):
                action = str((query_params.get("action") or [""])[0]).strip().lower()
                rule_id = str((query_params.get("ruleId") or [""])[0]).strip()
                if action == "ruleinfo" and rule_id.isdigit():
                    display_rule_urls.append(link_url)
        if len(display_rule_urls) >= max(8, int(limit) * 4):
            break

    for display_rule_url in _dedupe(display_rule_urls)[: max(8, int(limit) * 4)]:
        scraped = await _scrape(display_rule_url)
        if scraped is None:
            continue
        html = str(getattr(scraped, "html", "") or "")
        for pdf_url in _colorado_latest_pdf_urls_from_html(html=html, base_url=display_rule_url):
            if _record(pdf_url):
                return discovered_urls

    return discovered_urls


async def _discover_georgia_rule_document_urls(*, seed_urls: List[str], limit: int = 8) -> List[str]:
    discovered_urls: List[str] = []
    seen_document_keys: set[str] = set()
    allowed_hosts = {"rules.sos.ga.gov"}
    request_headers = {"User-Agent": "Mozilla/5.0"}

    def _record(url: str) -> bool:
        key = _url_key(url)
        if not key or key in seen_document_keys:
            return False
        seen_document_keys.add(key)
        discovered_urls.append(url)
        return len(discovered_urls) >= max(1, int(limit))

    def _dedupe(values: List[str]) -> List[str]:
        deduped: List[str] = []
        seen_keys: set[str] = set()
        for value in values:
            key = _url_key(value)
            if not key or key in seen_keys:
                continue
            seen_keys.add(key)
            deduped.append(value)
        return deduped

    async def _fetch_links(page_url: str, *, limit_n: int) -> List[str]:
        try:
            response = await asyncio.to_thread(
                requests.get,
                page_url,
                timeout=20,
                headers=request_headers,
            )
            response.raise_for_status()
            html = str(response.text or "")
        except Exception:
            return []

        candidate_links = _candidate_links_from_html(
            html,
            base_host="rules.sos.ga.gov",
            page_url=page_url,
            limit=limit_n,
            allowed_hosts=allowed_hosts,
        )
        candidate_links.sort(key=_georgia_bootstrap_priority, reverse=True)
        return _dedupe(candidate_links)

    root_url = "https://rules.sos.ga.gov/gac"
    for seed_url in seed_urls:
        seed_value = str(seed_url or "").strip()
        parsed = urlparse(seed_value)
        if parsed.netloc.lower() == "rules.sos.ga.gov" and (parsed.path or "").rstrip("/").lower() == "/gac":
            root_url = seed_value.rstrip("/")
            break

    department_urls = [
        link_url
        for link_url in await _fetch_links(root_url, limit_n=64)
        if _GA_GAC_DEPARTMENT_PATH_RE.fullmatch(urlparse(link_url).path or "")
    ][:6]

    chapter_urls: List[str] = []
    for department_url in department_urls:
        chapter_urls.extend(
            link_url
            for link_url in await _fetch_links(department_url, limit_n=32)
            if _GA_GAC_CHAPTER_PATH_RE.fullmatch(urlparse(link_url).path or "")
        )
        if len(chapter_urls) >= 18:
            break
    chapter_urls = _dedupe(chapter_urls)[:18]

    subject_urls: List[str] = []
    for chapter_url in chapter_urls:
        for link_url in await _fetch_links(chapter_url, limit_n=32):
            path = urlparse(link_url).path or ""
            if _GA_GAC_RULE_PATH_RE.fullmatch(path):
                if _record(link_url):
                    return discovered_urls
                continue
            if _GA_GAC_SUBJECT_PATH_RE.fullmatch(path):
                subject_urls.append(link_url)
        if len(subject_urls) >= 24:
            break
    subject_urls = _dedupe(subject_urls)[:24]

    for subject_url in subject_urls:
        for link_url in await _fetch_links(subject_url, limit_n=24):
            if _GA_GAC_RULE_PATH_RE.fullmatch(urlparse(link_url).path or ""):
                if _record(link_url):
                    return discovered_urls

    return discovered_urls


async def _discover_kansas_rule_document_urls(*, seed_urls: List[str], live_scraper: Any, limit: int = 8) -> List[str]:
    discovered_urls: List[str] = []
    seen_document_keys: set[str] = set()
    seen_listing_keys: set[str] = set()
    listing_urls: List[str] = []

    def _record_document(url: str) -> bool:
        key = _url_key(url)
        if not key or key in seen_document_keys:
            return False
        seen_document_keys.add(key)
        discovered_urls.append(url)
        return len(discovered_urls) >= max(1, int(limit))

    def _record_listing(url: str) -> None:
        key = _url_key(url)
        if not key or key in seen_listing_keys:
            return
        seen_listing_keys.add(key)
        listing_urls.append(url)

    root_url = "https://www.sos.ks.gov/publications/pubs_kar.aspx"
    for seed_url in seed_urls:
        seed_value = str(seed_url or "").strip()
        parsed = urlparse(seed_value)
        if parsed.netloc.lower() != "www.sos.ks.gov":
            continue
        normalized_path = (parsed.path or "").lower()
        if normalized_path == "/publications/pubs_kar.aspx":
            root_url = seed_value
            continue
        if normalized_path != "/publications/pubs_kar_regs.aspx":
            continue
        kar_value = str((parse_qs(parsed.query or "").get("KAR") or [""])[0]).strip()
        if re.fullmatch(r"\d{1,3}(?:-\d{1,3})?", kar_value):
            _record_listing(seed_value)

    try:
        root_scraped = await asyncio.wait_for(live_scraper.scrape(root_url), timeout=15.0)
    except Exception:
        root_scraped = None
    root_text = str(getattr(root_scraped, "text", "") or "")
    for agency_number in re.findall(r"(?m)^\s*(\d{1,3})\s*-\s+[^\n]+$", root_text):
        _record_listing(
            f"https://www.sos.ks.gov/publications/pubs_kar_Regs.aspx?KAR={quote(str(agency_number))}&Srch=Y"
        )
        if len(listing_urls) >= min(max(max(1, int(limit)) * 2, 8), 16):
            break

    max_listing_urls = min(len(listing_urls), max(max(1, int(limit)) * 2, 8))
    for listing_url in listing_urls[:max_listing_urls]:
        try:
            listing_scraped = await asyncio.wait_for(live_scraper.scrape(listing_url), timeout=15.0)
        except Exception:
            continue
        listing_text = str(getattr(listing_scraped, "text", "") or "")
        for match in re.finditer(r"(\d{1,3}-\d{1,3}-\d+[A-Za-z-]*)\.\s+([^\n]+)", listing_text):
            rule_number = str(match.group(1) or "").strip()
            rule_title = str(match.group(2) or "").strip()
            if not rule_number:
                continue
            if rule_title.lower().startswith("revoked"):
                continue
            detail_url = f"https://www.sos.ks.gov/publications/pubs_kar_Regs.aspx?KAR={quote(rule_number)}&Srch=Y"
            if _record_document(detail_url):
                return discovered_urls

    return discovered_urls


async def _discover_idaho_rule_document_urls(*, seed_urls: List[str], live_scraper: Any, limit: int = 8) -> List[str]:
    discovered_urls: List[str] = []
    seen_document_keys: set[str] = set()
    allowed_hosts = {
        "adminrules.idaho.gov",
        "stagingdfmmainsa.blob.core.windows.net",
        "proddfmmainsa.blob.core.windows.net",
    }
    request_headers = {"User-Agent": "Mozilla/5.0"}

    def _record(url: str) -> bool:
        key = _url_key(url)
        if not key or key in seen_document_keys:
            return False
        seen_document_keys.add(key)
        discovered_urls.append(url)
        return len(discovered_urls) >= max(1, int(limit))

    current_rules_url = "https://adminrules.idaho.gov/current-rules/"
    for seed_url in seed_urls:
        seed_value = str(seed_url or "").strip()
        parsed = urlparse(seed_value)
        if parsed.netloc.lower() == "adminrules.idaho.gov" and (parsed.path or "").rstrip("/").lower() in {
            "/current-rules",
            "/rules/current",
        }:
            current_rules_url = seed_value.rstrip("/") + "/"
            break

    def _extract_links(html: str) -> List[str]:
        candidate_links: List[str] = []
        soup = BeautifulSoup(html, "html.parser")
        for anchor in soup.find_all("a", href=True):
            href = str(anchor.get("href") or "").strip()
            if not href:
                continue
            absolute_url = urljoin(current_rules_url, href)
            parsed = urlparse(absolute_url)
            host = parsed.netloc.lower().strip(".")
            path = (parsed.path or "").lower()
            if host not in allowed_hosts:
                continue
            if not path.endswith(".pdf"):
                continue
            if "/rules/current/" not in path:
                continue
            candidate_links.append(absolute_url)

        candidate_links.sort(key=_score_candidate_url, reverse=True)
        return candidate_links

    html = ""
    try:
        scraped = await asyncio.wait_for(live_scraper.scrape(current_rules_url), timeout=15.0)
        html = str(getattr(scraped, "html", "") or "")
    except Exception:
        html = ""

    if not html:
        def _fetch_html() -> str:
            response = requests.get(
                current_rules_url,
                timeout=20,
                headers=request_headers,
            )
            response.raise_for_status()
            return str(response.text or "")

        try:
            html = await asyncio.wait_for(asyncio.to_thread(_fetch_html), timeout=25.0)
        except Exception:
            html = ""

    if not html:
        return discovered_urls

    if not _extract_links(html):
        try:
            from ..web_archiving.unified_web_scraper import (
                ScraperConfig as _ScraperConfig,
                ScraperMethod as _ScraperMethod,
                UnifiedWebScraper as _UnifiedWebScraper,
            )
        except Exception:
            try:
                from ipfs_datasets_py.processors.web_archiving.unified_web_scraper import (  # type: ignore[no-redef]
                    ScraperConfig as _ScraperConfig,
                    ScraperMethod as _ScraperMethod,
                    UnifiedWebScraper as _UnifiedWebScraper,
                )
            except Exception:
                _ScraperConfig = None  # type: ignore[assignment]
                _ScraperMethod = None  # type: ignore[assignment]
                _UnifiedWebScraper = None  # type: ignore[assignment]

        if _UnifiedWebScraper is not None and _ScraperConfig is not None and _ScraperMethod is not None:
            try:
                playwright_scraper = _UnifiedWebScraper(
                    _ScraperConfig(
                        timeout=25,
                        max_retries=1,
                        extract_links=True,
                        extract_text=True,
                        fallback_enabled=False,
                        playwright_hydration_wait_ms=2000,
                        preferred_methods=[_ScraperMethod.PLAYWRIGHT],
                    )
                )
                playwright_scraped = await asyncio.wait_for(playwright_scraper.scrape(current_rules_url), timeout=30.0)
                playwright_html = str(getattr(playwright_scraped, "html", "") or "")
                if playwright_html:
                    html = playwright_html
            except Exception:
                pass

    if not _extract_links(html):
        try:
            from ..playwright_limiter import acquire_playwright_slot as _acquire_playwright_slot
        except Exception:
            try:
                from ipfs_datasets_py.processors.playwright_limiter import acquire_playwright_slot as _acquire_playwright_slot  # type: ignore[no-redef]
            except Exception:
                _acquire_playwright_slot = None  # type: ignore[assignment]
        try:
            from playwright.async_api import async_playwright as _async_playwright
        except Exception:
            _async_playwright = None  # type: ignore[assignment]

        if _acquire_playwright_slot is not None and _async_playwright is not None:
            try:
                async with _acquire_playwright_slot():
                    async with _async_playwright() as playwright:
                        browser = await playwright.chromium.launch(headless=True)
                        try:
                            page = await browser.new_page()
                            await page.goto(current_rules_url, wait_until="networkidle", timeout=25000)
                            await page.wait_for_timeout(2000)
                            playwright_html = await page.content()
                            if playwright_html:
                                html = str(playwright_html)
                        finally:
                            await browser.close()
            except Exception:
                pass

    for document_url in _extract_links(html):
        if _record(document_url):
            break

    return discovered_urls


async def _discover_maryland_rule_document_urls(*, seed_urls: List[str], limit: int = 8) -> List[str]:
    discovered_urls: List[str] = []
    fallback_urls: List[str] = []
    seen_document_keys: set[str] = set()
    seen_page_keys: set[str] = set()

    def _dedupe_urls(values: List[str]) -> List[str]:
        seen_values: set[str] = set()
        deduped: List[str] = []
        for value in values:
            key = _url_key(value)
            if not key or key in seen_values:
                continue
            seen_values.add(key)
            deduped.append(value)
        return deduped

    def _record(url: str) -> bool:
        key = _url_key(url)
        if not key or key in seen_document_keys:
            return False
        seen_document_keys.add(key)
        discovered_urls.append(url)
        return len(discovered_urls) >= max(1, int(limit))

    def _record_fallback(url: str) -> None:
        key = _url_key(url)
        if not key or key in seen_document_keys:
            return
        seen_document_keys.add(key)
        fallback_urls.append(url)

    def _page_priority(url: str) -> tuple[int, int, str]:
        path = urlparse(url).path or ""
        dots = path.rstrip("/").split("/")[-1].count(".") if path else 0
        if dots >= 2:
            return (3, dots, url)
        if dots == 1:
            return (2, dots, url)
        return (1, dots, url)

    def _fetch_links(page_url: str) -> List[str]:
        try:
            response = requests.get(page_url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
            response.raise_for_status()
        except Exception:
            return []

        soup = BeautifulSoup(response.text or "", "html.parser")
        links: List[str] = []
        for anchor in soup.find_all("a", href=True):
            absolute_url = urldefrag(urljoin(page_url, str(anchor.get("href") or "").strip())).url
            parsed = urlparse(absolute_url)
            if parsed.netloc.lower() != "regs.maryland.gov":
                continue
            if not (parsed.path or "").startswith("/us/md/exec/comar"):
                continue
            links.append(absolute_url)
        return _dedupe_urls(links)

    frontier = [
        urldefrag(url).url
        for url in seed_urls
        if urlparse(str(url or "").strip()).netloc.lower() == "regs.maryland.gov"
    ]
    frontier = sorted(_dedupe_urls(frontier), key=_page_priority, reverse=True)

    for _depth in range(3):
        next_frontier: List[str] = []
        for page_url in frontier[:6]:
            page_key = _url_key(page_url)
            if not page_key or page_key in seen_page_keys:
                continue
            seen_page_keys.add(page_key)

            for link_url in _fetch_links(page_url):
                path = urlparse(link_url).path or ""
                dot_count = path.rstrip("/").split("/")[-1].count(".") if path else 0
                if _MD_COMAR_DETAIL_PATH_RE.search(path):
                    if dot_count >= 3:
                        if _record(link_url):
                            return discovered_urls
                        continue
                    if dot_count == 2:
                        _record_fallback(link_url)
                        next_frontier.append(link_url)
                        continue
                if _MD_COMAR_INVENTORY_PATH_RE.search(path):
                    if dot_count >= 2:
                        _record_fallback(link_url)
                    next_frontier.append(link_url)
        if not next_frontier:
            break
        frontier = sorted(_dedupe_urls(next_frontier), key=_page_priority, reverse=True)

    if discovered_urls:
        return discovered_urls
    return fallback_urls[: max(1, int(limit))]


async def _discover_maine_rule_document_urls(*, seed_urls: List[str], limit: int = 8) -> List[str]:
    discovered_urls: List[str] = []
    seen_document_keys: set[str] = set()
    seen_department_keys: set[str] = set()
    department_urls: List[str] = []
    root_url = "https://www.maine.gov/sos/rulemaking/agency-rules"

    def _record_document(url: str) -> bool:
        key = _url_key(url)
        if not key or key in seen_document_keys:
            return False
        seen_document_keys.add(key)
        discovered_urls.append(url)
        return len(discovered_urls) >= max(1, int(limit))

    def _record_department(url: str) -> None:
        key = _url_key(url)
        if not key or key in seen_department_keys:
            return
        seen_department_keys.add(key)
        department_urls.append(url)

    def _fetch_html(page_url: str) -> str:
        try:
            response = requests.get(page_url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
            response.raise_for_status()
        except Exception:
            return ""
        return str(response.text or "")

    for seed_url in seed_urls:
        seed_value = urldefrag(str(seed_url or "").strip()).url
        parsed = urlparse(seed_value)
        if parsed.netloc.lower() not in {"www.maine.gov", "maine.gov"}:
            continue
        if _ME_RULE_DEPARTMENT_PATH_RE.search(parsed.path or ""):
            _record_department(seed_value)
        elif _ME_RULES_INDEX_PATH_RE.search(parsed.path or ""):
            root_url = seed_value

    if len(department_urls) < 3:
        root_html = _fetch_html(root_url)
        if root_html:
            soup = BeautifulSoup(root_html, "html.parser")
            for anchor in soup.find_all("a", href=True):
                absolute_url = urldefrag(urljoin(root_url, str(anchor.get("href") or "").strip())).url
                parsed = urlparse(absolute_url)
                if parsed.netloc.lower() not in {"www.maine.gov", "maine.gov"}:
                    continue
                if _ME_RULE_DEPARTMENT_PATH_RE.search(parsed.path or ""):
                    _record_department(absolute_url)
                if len(department_urls) >= 6:
                    break

    for department_url in department_urls[:6]:
        department_html = _fetch_html(department_url)
        if not department_html:
            continue
        soup = BeautifulSoup(department_html, "html.parser")
        for anchor in soup.find_all("a", href=True):
            href = str(anchor.get("href") or "").strip()
            if not href:
                continue
            absolute_url = urldefrag(urljoin(department_url, href)).url
            parsed = urlparse(absolute_url)
            if parsed.netloc.lower() not in {"www.maine.gov", "maine.gov"}:
                continue
            path = parsed.path or ""
            if _is_docx_candidate_url(absolute_url) or _is_pdf_candidate_url(absolute_url):
                if _record_document(absolute_url):
                    return discovered_urls
                continue
            if path.startswith("/sos/rulemaking/agency-rules/") and path != urlparse(department_url).path:
                link_text = re.sub(r"\s+", " ", anchor.get_text(" ", strip=True) or "").strip()
                if re.search(r"\b(?:manual|rule|regulation)\b", link_text, re.IGNORECASE):
                    if _record_document(absolute_url):
                        return discovered_urls

    return discovered_urls


def _nebraska_sort_key(value: Any) -> tuple[int | str, ...]:
    parts = re.findall(r"\d+|[A-Za-z]+", str(value or ""))
    if not parts:
        return (999999, "")
    key: List[int | str] = []
    for part in parts:
        if part.isdigit():
            key.extend((0, int(part)))
        else:
            key.extend((1, part.lower()))
    return tuple(key)


def _nebraska_file_storage_download_url(container_name: str, blob_name: str) -> str:
    container = quote(str(container_name or "").strip().strip("/"), safe="-._~")
    blob = quote(str(blob_name or "").strip(), safe="()!$&'*,;=:@-._~")
    return f"{_NE_RULES_API_BASE_URL}/fileStorage/GetAsByteArray/{container}/{blob}"


def _nebraska_output_list(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, dict):
        payload = payload.get("output")
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


async def _discover_nebraska_rule_document_urls(*, limit: int = 8) -> List[str]:
    limit_n = max(1, int(limit))

    def _run() -> List[str]:
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json,text/plain,*/*",
        }
        session = requests.Session()
        discovered_urls: List[str] = []
        inventory_urls: List[str] = []
        seen_document_keys: set[str] = set()
        seen_inventory_keys: set[str] = set()

        def _get_json(url: str) -> Any:
            try:
                response = session.get(url, timeout=20, headers=headers)
            except requests.exceptions.SSLError:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    response = session.get(url, timeout=20, headers=headers, verify=False)
            response.raise_for_status()
            return response.json()

        try:
            titles_payload = _get_json(f"{_NE_RULES_API_BASE_URL}/title")
        except Exception:
            return []

        titles = sorted(
            _nebraska_output_list(titles_payload),
            key=lambda item: (
                _nebraska_sort_key(item.get("titleNumber")),
                _nebraska_sort_key(item.get("titleName")),
                int(item.get("id") or 0),
            ),
        )

        for title in titles:
            title_id = str(title.get("id") or "").strip()
            agency_id = str(title.get("agencyId") or "").strip()
            if not title_id.isdigit():
                continue
            if agency_id.isdigit():
                inventory_url = f"https://rules.nebraska.gov/rules?agencyId={agency_id}&titleId={title_id}"
                inventory_key = _url_key(inventory_url)
                if inventory_key and inventory_key not in seen_inventory_keys:
                    seen_inventory_keys.add(inventory_key)
                    inventory_urls.append(inventory_url)

            try:
                chapters_payload = _get_json(f"{_NE_RULES_API_BASE_URL}/chapter/GetByTitleId/{title_id}")
            except Exception:
                continue

            chapters = sorted(
                _nebraska_output_list(chapters_payload),
                key=lambda item: (
                    _nebraska_sort_key(item.get("chapterNumber")),
                    _nebraska_sort_key(item.get("chapterName")),
                    int(item.get("id") or 0),
                ),
            )
            for chapter in chapters:
                container_name = str(chapter.get("pdfContainerName") or "chapter-pdfs").strip() or "chapter-pdfs"
                blob_name = str(chapter.get("officialPdfBlobName") or chapter.get("pdfBlobName") or "").strip()
                if not blob_name:
                    continue
                document_url = _nebraska_file_storage_download_url(container_name, blob_name)
                document_key = _url_key(document_url)
                if not document_key or document_key in seen_document_keys:
                    continue
                seen_document_keys.add(document_key)
                discovered_urls.append(document_url)
                if len(discovered_urls) >= limit_n:
                    return discovered_urls

        return discovered_urls or inventory_urls[:limit_n]

    try:
        return await _run_state_worker(_run)
    except Exception:
        return []


async def _discover_california_westlaw_document_urls(
    *,
    seed_urls: List[str],
    live_scraper: Any,
    live_fetch_api: Any,
    direct_fetch_api: Any,
    allowed_hosts: set[str],
    limit: int = 8,
) -> List[str]:
    try:
        from ..web_archiving.unified_api import UnifiedWebArchivingAPI as _UnifiedWebArchivingAPI
        from ..web_archiving.unified_web_scraper import (
            ScraperConfig as _ScraperConfig,
            ScraperMethod as _ScraperMethod,
            UnifiedWebScraper as _UnifiedWebScraper,
        )
    except Exception:
        try:
            from ipfs_datasets_py.processors.web_archiving.unified_api import UnifiedWebArchivingAPI as _UnifiedWebArchivingAPI  # type: ignore[no-redef]
            from ipfs_datasets_py.processors.web_archiving.unified_web_scraper import (  # type: ignore[no-redef]
                ScraperConfig as _ScraperConfig,
                ScraperMethod as _ScraperMethod,
                UnifiedWebScraper as _UnifiedWebScraper,
            )
        except Exception:
            _UnifiedWebArchivingAPI = None  # type: ignore[assignment]
            _ScraperConfig = None  # type: ignore[assignment]
            _ScraperMethod = None  # type: ignore[assignment]
            _UnifiedWebScraper = None  # type: ignore[assignment]

    frontier: List[str] = [
        url
        for url in seed_urls
        if urlparse(str(url or "").strip()).netloc.lower() == "govt.westlaw.com"
    ]
    if not frontier:
        return []

    document_urls: List[str] = []
    seen_pages: set[str] = set()
    seen_documents: set[str] = set()

    def _has_useful_california_westlaw_links(candidate_links: List[str]) -> bool:
        for candidate_url in candidate_links:
            candidate_path = (urlparse(candidate_url).path or "").lower()
            if candidate_path.startswith("/calregs/document/"):
                return True
            if candidate_path.startswith("/calregs/browse/home/california/californiacodeofregulations"):
                return True
        return False

    for _depth in range(5):
        next_frontier: List[str] = []
        # This bootstrap is only meant to prime the main traversal with a small
        # number of concrete document URLs. Keep the breadth narrow so bounded
        # daemon cycles still have budget left to fetch the discovered rules.
        for page_url in frontier[:2]:
            page_key = _url_key(page_url)
            if not page_key or page_key in seen_pages:
                continue
            seen_pages.add(page_key)

            html = ""
            scraped = None
            page_host = urlparse(page_url).netloc
            fetch_api = live_fetch_api if _prefers_live_fetch(page_url) else direct_fetch_api
            try:
                fetched = await asyncio.wait_for(
                    _run_blocking_fetch(
                        fetch_api.fetch,
                        UnifiedFetchRequest(
                            url=page_url,
                            timeout_seconds=15,
                            mode=OperationMode.BALANCED,
                            domain=".gov" if page_host.endswith(".gov") else "legal",
                        ),
                    ),
                    timeout=6.0,
                )
                fetched_doc = getattr(fetched, "document", None)
                html = str(getattr(fetched_doc, "html", "") or "")
            except Exception:
                html = ""

            if not html:
                try:
                    scraped = await asyncio.wait_for(live_scraper.scrape(page_url), timeout=6.0)
                    html = str(getattr(scraped, "html", "") or "")
                except Exception:
                    scraped = None

            if not html and _UnifiedWebScraper is not None and _ScraperConfig is not None and _ScraperMethod is not None:
                try:
                    request_only_scraper = _UnifiedWebScraper(
                        _ScraperConfig(
                            timeout=20,
                            max_retries=1,
                            extract_links=True,
                            extract_text=True,
                            fallback_enabled=False,
                            preferred_methods=[_ScraperMethod.REQUESTS_ONLY],
                        )
                    )
                    request_only_scraped = await asyncio.wait_for(
                        request_only_scraper.scrape(page_url),
                        timeout=6.0,
                    )
                    request_only_html = str(getattr(request_only_scraped, "html", "") or "")
                    if request_only_html:
                        scraped = request_only_scraped
                        html = request_only_html
                except Exception:
                    pass

            links = _candidate_links_from_html(
                html,
                base_host="govt.westlaw.com",
                page_url=page_url,
                limit=24,
                allowed_hosts=allowed_hosts,
            )
            if scraped is not None:
                for link_url in _candidate_links_from_scrape(
                    scraped,
                    base_host="govt.westlaw.com",
                    page_url=page_url,
                    limit=24,
                    allowed_hosts=allowed_hosts,
                ):
                    if link_url not in links:
                        links.append(link_url)

            if (
                not _has_useful_california_westlaw_links(links)
                and _UnifiedWebScraper is not None
                and _ScraperConfig is not None
                and _ScraperMethod is not None
            ):
                try:
                    request_only_scraper = _UnifiedWebScraper(
                        _ScraperConfig(
                            timeout=20,
                            max_retries=1,
                            extract_links=True,
                            extract_text=True,
                            fallback_enabled=False,
                            preferred_methods=[_ScraperMethod.REQUESTS_ONLY],
                        )
                    )
                    request_only_scraped = await asyncio.wait_for(
                        request_only_scraper.scrape(page_url),
                        timeout=6.0,
                    )
                    request_only_html = str(getattr(request_only_scraped, "html", "") or "")
                    request_only_links = _candidate_links_from_html(
                        request_only_html,
                        base_host="govt.westlaw.com",
                        page_url=page_url,
                        limit=24,
                        allowed_hosts=allowed_hosts,
                    )
                    for link_url in _candidate_links_from_scrape(
                        request_only_scraped,
                        base_host="govt.westlaw.com",
                        page_url=page_url,
                        limit=24,
                        allowed_hosts=allowed_hosts,
                    ):
                        if link_url not in request_only_links:
                            request_only_links.append(link_url)
                    if _has_useful_california_westlaw_links(request_only_links):
                        scraped = request_only_scraped
                        html = request_only_html
                        links = request_only_links
                except Exception:
                    pass

            for link_url in links:
                if urlparse(link_url).path.lower().startswith("/calregs/document/"):
                    document_key = _url_key(link_url)
                    if not document_key or document_key in seen_documents:
                        continue
                    seen_documents.add(document_key)
                    document_urls.append(link_url)
                    if len(document_urls) >= max(1, int(limit)):
                        return document_urls

            for link_url in links:
                if not urlparse(link_url).path.lower().startswith("/calregs/browse/home/california/californiacodeofregulations"):
                    continue
                link_key = _url_key(link_url)
                if not link_key or link_key in seen_pages:
                    continue
                if link_url not in next_frontier:
                    next_frontier.append(link_url)

        frontier = next_frontier
        if not frontier:
            break

    return document_urls


def _write_agentic_kg_corpus_jsonl(rows: List[Dict[str, Any]], output_root: Path) -> Optional[str]:
    if not rows:
        return None
    out_dir = output_root / "agentic_discovery"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "state_admin_rule_kg_corpus.jsonl"
    with out_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            if not isinstance(row, dict):
                continue
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return str(out_path)


def _iter_cloudflare_metadata_mappings(candidate: Any) -> List[Dict[str, Any]]:
    pending: List[Any] = [candidate]
    seen: set[int] = set()
    mappings: List[Dict[str, Any]] = []
    while pending:
        value = pending.pop(0)
        if value is None:
            continue
        value_id = id(value)
        if value_id in seen:
            continue
        seen.add(value_id)
        if isinstance(value, dict):
            mappings.append(value)
            for nested_key in ("metadata", "extraction_provenance", "document"):
                nested_value = value.get(nested_key)
                if nested_value is not None:
                    pending.append(nested_value)
            continue
        for nested_attr in ("metadata", "extraction_provenance", "document"):
            nested_value = getattr(value, nested_attr, None)
            if nested_value is not None:
                pending.append(nested_value)
    return mappings


def _extract_cloudflare_rate_limit_metadata(candidate: Any) -> Dict[str, Any]:
    for mapping in _iter_cloudflare_metadata_mappings(candidate):
        status = str(mapping.get("cloudflare_status") or "").strip().lower()
        provider = str(mapping.get("provider") or "").strip().lower()
        method = str(mapping.get("method") or mapping.get("method_used") or "").strip().lower()
        http_status = mapping.get("cloudflare_http_status", mapping.get("status"))
        try:
            normalized_http_status = int(http_status) if http_status is not None and str(http_status).strip() else None
        except (TypeError, ValueError):
            normalized_http_status = None
        record_status = str(mapping.get("cloudflare_record_status") or "").strip().lower()
        has_signal = (
            status in {"rate_limited", "browser_challenge", "record_errored", "error"}
            or mapping.get("retry_after_seconds") is not None
            or mapping.get("retry_at_utc") is not None
            or mapping.get("rate_limit_diagnostics") is not None
            or bool(mapping.get("wait_budget_exhausted"))
            or bool(mapping.get("cloudflare_browser_challenge_detected"))
            or normalized_http_status is not None and normalized_http_status >= 400
            or record_status in {"errored", "failed", "timed_out"}
        )
        if not has_signal:
            continue
        extracted = {
            "cloudflare_status": status or None,
            "retry_after_seconds": mapping.get("retry_after_seconds"),
            "retry_at_utc": mapping.get("retry_at_utc"),
            "retryable": mapping.get("retryable"),
            "wait_budget_exhausted": mapping.get("wait_budget_exhausted"),
            "rate_limit_diagnostics": mapping.get("rate_limit_diagnostics"),
            "cloudflare_http_status": mapping.get("cloudflare_http_status", mapping.get("status")),
            "cloudflare_browser_challenge_detected": mapping.get("cloudflare_browser_challenge_detected"),
            "cloudflare_error_excerpt": mapping.get("cloudflare_error_excerpt"),
            "cloudflare_record_status": mapping.get("cloudflare_record_status"),
            "cloudflare_job_status": mapping.get("cloudflare_job_status"),
        }
        if provider:
            extracted["provider"] = provider
        if method:
            extracted["method"] = method
        return {key: value for key, value in extracted.items() if value is not None}
    return {}


def _merge_cloudflare_rate_limit_metadata(current: Dict[str, Any], candidate: Any) -> Dict[str, Any]:
    candidate_metadata = _extract_cloudflare_rate_limit_metadata(candidate)
    if not candidate_metadata:
        return dict(current or {})
    if not current:
        return dict(candidate_metadata)

    merged = dict(current)
    current_status = str(merged.get("cloudflare_status") or "").strip().lower()
    candidate_status = str(candidate_metadata.get("cloudflare_status") or "").strip().lower()
    if current_status != "rate_limited" and candidate_status == "rate_limited":
        merged.update(candidate_metadata)
        return merged

    if current_status not in {"rate_limited", "browser_challenge"} and candidate_status == "browser_challenge":
        merged.update(candidate_metadata)
        return merged

    if "rate_limit_diagnostics" in candidate_metadata and "rate_limit_diagnostics" in merged:
        merged["rate_limit_diagnostics"] = {
            **dict(merged.get("rate_limit_diagnostics") or {}),
            **dict(candidate_metadata.get("rate_limit_diagnostics") or {}),
        }
    for key, value in candidate_metadata.items():
        if key == "rate_limit_diagnostics":
            continue
        if merged.get(key) is None and value is not None:
            merged[key] = value
    return merged


def _cloudflare_browser_rendering_availability() -> Dict[str, Any]:
    account_env_keys = [
        "IPFS_DATASETS_CLOUDFLARE_ACCOUNT_ID",
        "LEGAL_SCRAPER_CLOUDFLARE_ACCOUNT_ID",
        "CLOUDFLARE_ACCOUNT_ID",
    ]
    token_env_keys = [
        "IPFS_DATASETS_CLOUDFLARE_API_TOKEN",
        "LEGAL_SCRAPER_CLOUDFLARE_API_TOKEN",
        "CLOUDFLARE_API_TOKEN",
    ]

    def _resolve_source(names: List[str], *, provider: str) -> Optional[str]:
        if provider == "env":
            return next((key for key in names if str(os.getenv(key) or "").strip()), None)
        if provider == "vault":
            try:
                from ipfs_datasets_py.mcp_server.secrets_vault import get_secrets_vault

                vault = get_secrets_vault()
                return next((key for key in names if str(vault.get(key) or "").strip()), None)
            except Exception:
                return None
        if provider == "keyring":
            try:
                import keyring  # type: ignore

                return next(
                    (
                        key
                        for key in names
                        if str(keyring.get_password("ipfs_datasets_py", key) or "").strip()
                    ),
                    None,
                )
            except Exception:
                return None
        return None

    account_source = _resolve_source(account_env_keys, provider="env")
    account_source_kind = "env" if account_source else None
    if not account_source:
        account_source = _resolve_source(account_env_keys, provider="vault")
        account_source_kind = "vault" if account_source else None
    if not account_source:
        account_source = _resolve_source(account_env_keys, provider="keyring")
        account_source_kind = "keyring" if account_source else None

    token_source = _resolve_source(token_env_keys, provider="env")
    token_source_kind = "env" if token_source else None
    if not token_source:
        token_source = _resolve_source(token_env_keys, provider="vault")
        token_source_kind = "vault" if token_source else None
    if not token_source:
        token_source = _resolve_source(token_env_keys, provider="keyring")
        token_source_kind = "keyring" if token_source else None

    missing_credentials: List[str] = []
    if not account_source:
        missing_credentials.append("account_id")
    if not token_source:
        missing_credentials.append("api_token")

    configured = not missing_credentials
    return {
        "available": configured,
        "status": "configured" if configured else "missing_credentials",
        "provider": "cloudflare_browser_rendering",
        "account_id_env": account_source,
        "api_token_env": token_source,
        "account_id_source_kind": account_source_kind,
        "api_token_source_kind": token_source_kind,
        "missing_credentials": missing_credentials,
    }


async def _agentic_discover_admin_state_blocks(
    *,
    states: List[str],
    max_candidates_per_state: int,
    max_fetch_per_state: int,
    max_results_per_domain: int,
    max_hops: int,
    max_pages: int,
    min_full_text_chars: int,
    require_substantive_text: bool,
    fetch_concurrency: int,
    per_state_budget_seconds: float = 120.0,
    _force_asyncio_backend: bool = False,
) -> Dict[str, Any]:
    if not _force_asyncio_backend:
        try:
            import anyio
            import sniffio

            if sniffio.current_async_library() != "asyncio":
                return await anyio.to_thread.run_sync(
                    lambda: asyncio.run(
                        _agentic_discover_admin_state_blocks(
                            states=states,
                            max_candidates_per_state=max_candidates_per_state,
                            max_fetch_per_state=max_fetch_per_state,
                            max_results_per_domain=max_results_per_domain,
                            max_hops=max_hops,
                            max_pages=max_pages,
                            min_full_text_chars=min_full_text_chars,
                            require_substantive_text=require_substantive_text,
                            fetch_concurrency=fetch_concurrency,
                            per_state_budget_seconds=per_state_budget_seconds,
                            _force_asyncio_backend=True,
                        )
                    )
                )
        except Exception:
            pass

    archive_search_timeout_seconds = 40.0
    normalized_states = [str(state or "").upper() for state in list(states or []) if str(state or "").strip()]
    if len(normalized_states) > 1:
        max_parallel_states = min(len(normalized_states), 4)
        semaphore = asyncio.Semaphore(max_parallel_states)

        async def _run_single_state(single_state: str) -> Dict[str, Any]:
            async with semaphore:
                return await _run_state_worker(
                    lambda: asyncio.run(
                        _agentic_discover_admin_state_blocks(
                            states=[single_state],
                            max_candidates_per_state=max_candidates_per_state,
                            max_fetch_per_state=max_fetch_per_state,
                            max_results_per_domain=max_results_per_domain,
                            max_hops=max_hops,
                            max_pages=max_pages,
                            min_full_text_chars=min_full_text_chars,
                            require_substantive_text=require_substantive_text,
                            fetch_concurrency=fetch_concurrency,
                            per_state_budget_seconds=per_state_budget_seconds,
                        )
                    )
                )

        state_results = await asyncio.gather(
            *[_run_single_state(state_code) for state_code in normalized_states],
            return_exceptions=True,
        )

        blocks: List[Dict[str, Any]] = []
        kg_rows: List[Dict[str, Any]] = []
        report: Dict[str, Any] = {}
        errors: List[str] = []

        for state_code, state_result in zip(normalized_states, state_results):
            if isinstance(state_result, Exception):
                errors.append(f"{state_code}:{state_result}")
                report[state_code] = {
                    "candidate_urls": 0,
                    "inspected_urls": 0,
                    "expanded_urls": 0,
                    "fetched_rules": 0,
                    "source_breakdown": {},
                    "timed_out": False,
                    "error": str(state_result),
                }
                blocks.append(
                    {
                        "state_code": state_code,
                        "state_name": US_STATES.get(state_code, state_code),
                        "title": f"{US_STATES.get(state_code, state_code)} Administrative Rules",
                        "source": "Agentic web-archive discovery",
                        "source_url": None,
                        "scraped_at": datetime.now().isoformat(),
                        "statutes": [],
                        "rules_count": 0,
                        "schema_version": "1.0",
                        "normalized": True,
                    }
                )
                continue

            blocks.extend(list(state_result.get("state_blocks") or []))
            kg_rows.extend(list(state_result.get("kg_rows") or []))
            state_report = state_result.get("report") or {}
            if isinstance(state_report, dict):
                report.update(state_report)
            if str(state_result.get("status") or "").lower() == "error":
                errors.append(f"{state_code}:{state_result.get('error') or 'unknown_error'}")

        aggregated: Dict[str, Any] = {
            "status": "success" if not errors else ("partial" if blocks else "error"),
            "state_blocks": blocks,
            "kg_rows": kg_rows,
            "report": report,
            "parallel_state_workers": max_parallel_states,
        }
        if errors:
            aggregated["error"] = "; ".join(errors)
        return aggregated

    try:
        from ipfs_datasets_py.processors.legal_scrapers.legal_web_archive_search import LegalWebArchiveSearch
        from ipfs_datasets_py.processors.legal_scrapers.parallel_web_archiver import ParallelWebArchiver
        try:
            from ..web_archiving.contracts import OperationMode, UnifiedFetchRequest, UnifiedSearchRequest
            from ..web_archiving.unified_api import UnifiedWebArchivingAPI
            from ..web_archiving.unified_web_scraper import (
                ScraperConfig,
                ScraperMethod,
                UnifiedWebScraper,
            )
        except Exception:
            from ipfs_datasets_py.processors.web_archiving.contracts import OperationMode, UnifiedFetchRequest, UnifiedSearchRequest
            from ipfs_datasets_py.processors.web_archiving.unified_api import UnifiedWebArchivingAPI
            from ipfs_datasets_py.processors.web_archiving.unified_web_scraper import (
                ScraperConfig,
                ScraperMethod,
                UnifiedWebScraper,
            )
    except Exception as exc:
        return {
            "status": "error",
            "error": f"agentic_import_failed: {exc}",
            "state_blocks": [],
            "kg_rows": [],
            "report": {},
        }

    cloudflare_browser_rendering_method = getattr(ScraperMethod, "CLOUDFLARE_BROWSER_RENDERING", None)
    archive_preferred_methods = [
        ScraperMethod.COMMON_CRAWL,
        ScraperMethod.WAYBACK_MACHINE,
    ]
    if cloudflare_browser_rendering_method is not None:
        archive_preferred_methods.append(cloudflare_browser_rendering_method)
    archive_preferred_methods.extend(
        [
            ScraperMethod.PLAYWRIGHT,
            ScraperMethod.BEAUTIFULSOUP,
            ScraperMethod.REQUESTS_ONLY,
        ]
    )
    live_preferred_methods = []
    if cloudflare_browser_rendering_method is not None:
        live_preferred_methods.append(cloudflare_browser_rendering_method)
    live_preferred_methods.extend(
        [
            ScraperMethod.PLAYWRIGHT,
            ScraperMethod.BEAUTIFULSOUP,
            ScraperMethod.REQUESTS_ONLY,
            ScraperMethod.WAYBACK_MACHINE,
            ScraperMethod.COMMON_CRAWL,
        ]
    )

    cfg = ScraperConfig(
        timeout=40,
        max_retries=2,
        extract_links=True,
        extract_text=True,
        fallback_enabled=True,
        rate_limit_delay=0.2,
        preferred_methods=archive_preferred_methods,
    )
    live_cfg = ScraperConfig(
        timeout=40,
        max_retries=2,
        extract_links=True,
        extract_text=True,
        fallback_enabled=True,
        rate_limit_delay=0.2,
        preferred_methods=live_preferred_methods,
    )
    scraper = UnifiedWebScraper(cfg)
    live_scraper = UnifiedWebScraper(live_cfg)
    unified_api = UnifiedWebArchivingAPI(scraper=scraper)
    live_fetch_api = UnifiedWebArchivingAPI(scraper=UnifiedWebScraper(live_cfg))
    direct_fetch_api = UnifiedWebArchivingAPI()
    parallel_archiver = ParallelWebArchiver(max_concurrent=max(1, int(fetch_concurrency)), timeout=25)
    legal_archive = LegalWebArchiveSearch(auto_archive=False, use_hf_indexes=True)

    blocks: List[Dict[str, Any]] = []
    kg_rows: List[Dict[str, Any]] = []
    report: Dict[str, Any] = {}

    for state_code in states:
        state_start = time.monotonic()
        requested_per_state_budget_s = float(per_state_budget_seconds or 0.0)
        state_budget_is_unbounded = requested_per_state_budget_s <= 0.0
        # Keep agentic fallback bounded per state so staged runs keep moving, unless
        # the caller explicitly disables the time limit.
        per_state_budget_s = math.inf if state_budget_is_unbounded else max(1.0, requested_per_state_budget_s)
        presearch_budget_deadline = (
            math.inf
            if state_budget_is_unbounded
            else state_start + max(12.0, min(35.0, per_state_budget_s * 0.25))
        )
        state_name = US_STATES.get(state_code, state_code)
        relaxed_recovery = str(state_code or "").upper() in _RECOVERY_RELAXED_STATES
        query = _agentic_query_for_state(state_code)
        candidate_urls: List[str] = []
        source_breakdown: Dict[str, int] = {}
        max_fetch = max(1, int(max_fetch_per_state))
        state_fetch_cap = _max_fetch_cap_for_state(state_code)
        if state_fetch_cap is not None:
            max_fetch = min(max_fetch, state_fetch_cap)
        new_hampshire_bootstrap_diagnostics: Dict[str, Any] = {}
        az_fetch_diagnostics: Dict[str, Any] = {}
        allowed_hosts = _allowed_discovery_hosts_for_state(state_code, state_name)
        state_rate_limit_metadata: Dict[str, Any] = {}
        co_progress_enabled = state_code == "CO"

        def _record_co_progress(phase: str, **details: Any) -> None:
            if not co_progress_enabled:
                return
            detail_parts = []
            for key, value in details.items():
                if value is None:
                    continue
                detail_parts.append(f"{key}={value}")
            detail_suffix = f" {' '.join(detail_parts)}" if detail_parts else ""
            elapsed_s = max(0.0, time.monotonic() - state_start)
            print(f"co_progress phase={phase} elapsed_s={elapsed_s:.1f}{detail_suffix}", flush=True)

        def _init_az_phase(name: str) -> Dict[str, Any]:
            phase = az_fetch_diagnostics.get(name)
            if isinstance(phase, dict):
                return phase
            phase = {
                "attempted": 0,
                "success": 0,
                "timeout": 0,
                "none": 0,
                "error": 0,
                "skipped": 0,
                "fallback_success": 0,
                "max_timeout_s": 0.0,
                "max_elapsed_s": 0.0,
                "samples": [],
            }
            az_fetch_diagnostics[name] = phase
            return phase

        def _init_az_url_provenance(url: str) -> Dict[str, Any]:
            if state_code != "AZ" or not url:
                return {}
            url_provenance = az_fetch_diagnostics.get("url_provenance")
            if not isinstance(url_provenance, dict):
                url_provenance = {}
                az_fetch_diagnostics["url_provenance"] = url_provenance
            provenance = url_provenance.get(url)
            if isinstance(provenance, dict):
                return provenance
            provenance = {
                "attempts": [],
                "emitted": False,
            }
            url_provenance[url] = provenance
            return provenance

        def _init_az_emitted_documents() -> Dict[str, Any]:
            if state_code != "AZ":
                return {}
            emitted_documents = az_fetch_diagnostics.get("emitted_documents")
            if not isinstance(emitted_documents, dict):
                emitted_documents = {}
                az_fetch_diagnostics["emitted_documents"] = emitted_documents
            return emitted_documents

        def _mark_az_emitted_document(
            url: str,
            *,
            source_phase: str,
            title: str,
            method_value: Any,
        ) -> None:
            provenance = _init_az_url_provenance(url)
            if not provenance:
                return
            method_name = getattr(method_value, "value", method_value)
            emitted_documents = _init_az_emitted_documents()
            emitted_entry = emitted_documents.get(url)
            if not isinstance(emitted_entry, dict):
                emitted_entry = {}
                emitted_documents[url] = emitted_entry
            provenance["emitted"] = True
            provenance["accepted_phase"] = source_phase
            provenance["accepted_format"] = _document_format_for_url(url)
            if method_name:
                provenance["accepted_method"] = str(method_name)
            if title:
                provenance["accepted_title"] = str(title).strip()[:200]
            provenance.pop("superseded_by", None)
            emitted_entry["emitted"] = True
            emitted_entry["accepted_phase"] = source_phase
            emitted_entry["accepted_format"] = _document_format_for_url(url)
            emitted_entry["source_domain"] = urlparse(url).netloc
            if method_name:
                emitted_entry["accepted_method"] = str(method_name)
            if title:
                emitted_entry["accepted_title"] = str(title).strip()[:200]
            emitted_entry.pop("superseded_by", None)

        def _mark_az_superseded_document(url: str, replacement_url: str) -> None:
            provenance = _init_az_url_provenance(url)
            if not provenance:
                return
            provenance["emitted"] = False
            provenance["superseded_by"] = replacement_url
            emitted_documents = _init_az_emitted_documents()
            emitted_entry = emitted_documents.get(url)
            if isinstance(emitted_entry, dict):
                emitted_entry["emitted"] = False
                emitted_entry["superseded_by"] = replacement_url

        def _record_az_phase(
            name: str,
            *,
            url: str,
            outcome: str,
            timeout_s: float = 0.0,
            elapsed_s: float = 0.0,
            detail: str = "",
        ) -> None:
            if state_code != "AZ":
                return
            phase = _init_az_phase(name)
            if outcome != "skipped":
                phase["attempted"] = int(phase.get("attempted", 0)) + 1
            phase[outcome] = int(phase.get(outcome, 0)) + 1
            phase["max_timeout_s"] = max(float(phase.get("max_timeout_s", 0.0)), float(timeout_s or 0.0))
            phase["max_elapsed_s"] = max(float(phase.get("max_elapsed_s", 0.0)), float(elapsed_s or 0.0))
            provenance = _init_az_url_provenance(url)
            attempts = provenance.get("attempts") if isinstance(provenance, dict) else None
            if not isinstance(attempts, list):
                attempts = []
                if isinstance(provenance, dict):
                    provenance["attempts"] = attempts
            if isinstance(attempts, list) and len(attempts) < 16:
                attempt: Dict[str, Any] = {
                    "phase": name,
                    "outcome": outcome,
                }
                if timeout_s:
                    attempt["timeout_s"] = round(float(timeout_s), 2)
                if elapsed_s:
                    attempt["elapsed_s"] = round(float(elapsed_s), 2)
                if detail:
                    attempt["detail"] = detail[:160]
                attempts.append(attempt)
                if outcome in {"success", "fallback_success"}:
                    provenance["accepted_phase"] = name
            samples = phase.get("samples")
            if not isinstance(samples, list):
                samples = []
                phase["samples"] = samples
            if len(samples) < 8 and (outcome in {"timeout", "error", "none", "fallback_success"} or float(elapsed_s or 0.0) >= 20.0):
                sample: Dict[str, Any] = {
                    "url": url,
                    "outcome": outcome,
                }
                if timeout_s:
                    sample["timeout_s"] = round(float(timeout_s), 2)
                if elapsed_s:
                    sample["elapsed_s"] = round(float(elapsed_s), 2)
                if detail:
                    sample["detail"] = detail[:160]
                samples.append(sample)

        def _record_rate_limit_metadata(candidate: Any) -> None:
            nonlocal state_rate_limit_metadata
            state_rate_limit_metadata = _merge_cloudflare_rate_limit_metadata(state_rate_limit_metadata, candidate)

        seed_urls = _extract_seed_urls_for_state(state_code, state_name)
        if not seed_urls:
            seed_urls = [f"https://{state_code.lower()}.gov"]
        if (
            state_code == "AZ"
            and any(
                _is_immediate_direct_detail_candidate_url(seed_url) and _is_pdf_candidate_url(seed_url)
                for seed_url in seed_urls[:8]
            )
            and not any(
                _is_immediate_direct_detail_candidate_url(seed_url) and _is_rtf_candidate_url(seed_url)
                for seed_url in seed_urls[:8]
            )
        ):
            per_state_budget_s = max(per_state_budget_s, 110.0)
        ordered_seed_urls = sorted(seed_urls, key=_seed_prefetch_priority, reverse=True)

        # Always inspect curated seed entrypoints directly as ranked candidates.
        # Some states expose substantive rule indexes at the seed URL itself,
        # and agentic discovery may not re-emit that same page as a document.
        candidate_urls.extend(seed_urls)
        candidate_urls.extend(_template_admin_urls_for_state(state_code))

        utah_api_rule_urls: List[str] = []
        arizona_bootstrap_document_urls: List[str] = []
        arkansas_bootstrap_document_urls: List[str] = []
        texas_bootstrap_document_urls: List[str] = []
        oklahoma_bootstrap_document_urls: List[str] = []
        tennessee_bootstrap_document_urls: List[str] = []
        maryland_bootstrap_document_urls: List[str] = []
        maine_bootstrap_document_urls: List[str] = []
        preseed_substantive_url_keys: set[str] = set()

        # Utah's public search API already exposes canonical detail-page URLs.
        # Seed them immediately so bounded runs can hit substantive rule pages
        # without waiting for slower search/index fetches to expand first.
        if state_code == "UT":
            seen_utah_bootstrap_rule_keys: set[str] = set()
            utah_bootstrap_limit = min(
                max(1, int(max_fetch_per_state)),
                8 if per_state_budget_s >= 60.0 else 4,
            )
            for seed_url in ordered_seed_urls:
                if not _is_immediate_direct_detail_candidate_url(seed_url):
                    continue
                seed_key = _url_key(seed_url)
                if not seed_key or seed_key in seen_utah_bootstrap_rule_keys:
                    continue
                seen_utah_bootstrap_rule_keys.add(seed_key)
                candidate_urls.append(seed_url)
                utah_api_rule_urls.append(seed_url)
                source_breakdown["utah_direct_seed"] = int(source_breakdown.get("utah_direct_seed", 0)) + 1
                if len(utah_api_rule_urls) >= utah_bootstrap_limit:
                    break

            utah_seed_limit = max(0, utah_bootstrap_limit - len(utah_api_rule_urls))
            utah_bootstrap_seeds = sorted(
                ordered_seed_urls[:6],
                key=lambda value: (
                    1
                    if urlparse(value).path.startswith("/api/public/searchRuleDataTotal/")
                    else 0
                ),
                reverse=True,
            )
            for seed_url in utah_bootstrap_seeds:
                if utah_seed_limit <= 0:
                    break
                parsed_seed = urlparse(seed_url)
                if parsed_seed.netloc.lower() != "adminrules.utah.gov":
                    continue
                if not (
                    parsed_seed.path.startswith("/public/search")
                    or parsed_seed.path.startswith("/api/public/searchRuleDataTotal/")
                ):
                    continue
                utah_api_scan_limit = max(8, utah_seed_limit * 4)
                for rule_url in _candidate_utah_rule_urls_from_public_api(
                    url=seed_url,
                    limit=utah_api_scan_limit,
                ):
                    rule_key = _url_key(rule_url)
                    if not rule_key or rule_key in seen_utah_bootstrap_rule_keys:
                        continue
                    seen_utah_bootstrap_rule_keys.add(rule_key)
                    candidate_urls.append(rule_url)
                    utah_api_rule_urls.append(rule_url)
                    source_breakdown["utah_public_api"] = int(source_breakdown.get("utah_public_api", 0)) + 1
                    utah_seed_limit = max(0, utah_seed_limit - 1)
                    if utah_seed_limit <= 0:
                        break
                if utah_api_rule_urls:
                    break

        if state_code == "AZ":
            try:
                arizona_bootstrap_document_urls = await asyncio.wait_for(
                    _discover_arizona_rule_document_urls(
                        seed_urls=ordered_seed_urls[:6],
                        live_scraper=live_scraper,
                        live_fetch_api=live_fetch_api,
                        direct_fetch_api=direct_fetch_api,
                        limit=min(max(max_fetch_per_state * 4, 8), 16),
                    ),
                    timeout=20.0,
                )
            except Exception:
                arizona_bootstrap_document_urls = []
            for document_url in arizona_bootstrap_document_urls:
                candidate_urls.append(document_url)
            if arizona_bootstrap_document_urls:
                source_breakdown["arizona_public_services_bootstrap"] = len(arizona_bootstrap_document_urls)

        if state_code == "AR":
            arkansas_seed_limit = max(2, min(max(1, int(max_fetch_per_state)) * 3, int(max_candidates_per_state), 8))
            arkansas_bootstrap_document_urls = await _discover_arkansas_rule_document_urls(
                seed_urls=ordered_seed_urls[:6],
                limit=arkansas_seed_limit,
            )
            for document_url in arkansas_bootstrap_document_urls:
                candidate_urls.append(document_url)
            if arkansas_bootstrap_document_urls:
                source_breakdown["arkansas_sos_search_bootstrap"] = len(arkansas_bootstrap_document_urls)

        if state_code == "TX":
            texas_seed_limit = max(2, min(max(1, int(max_fetch_per_state)) * 3, int(max_candidates_per_state), 12))
            try:
                texas_bootstrap_document_urls = await asyncio.wait_for(
                    _discover_texas_rule_document_urls(
                        seed_urls=ordered_seed_urls[:6],
                        limit=texas_seed_limit,
                    ),
                    timeout=35.0,
                )
            except Exception:
                texas_bootstrap_document_urls = []
            for document_url in texas_bootstrap_document_urls:
                candidate_urls.append(document_url)
            if texas_bootstrap_document_urls:
                source_breakdown["texas_appian_bootstrap"] = len(texas_bootstrap_document_urls)

        if state_code == "OK":
            oklahoma_seed_limit = max(2, min(max(1, int(max_fetch_per_state)) * 3, int(max_candidates_per_state), 12))
            try:
                oklahoma_bootstrap_document_urls = await asyncio.wait_for(
                    _discover_oklahoma_rule_document_urls(limit=oklahoma_seed_limit),
                    timeout=25.0,
                )
            except Exception:
                oklahoma_bootstrap_document_urls = []
            for document_url in oklahoma_bootstrap_document_urls:
                candidate_urls.append(document_url)
            if oklahoma_bootstrap_document_urls:
                source_breakdown["oklahoma_rules_api_bootstrap"] = len(oklahoma_bootstrap_document_urls)

        seeded_direct_detail_urls = [url for url in seed_urls if _is_immediate_direct_detail_candidate_url(url)]

        if state_code == "MD" and len(seeded_direct_detail_urls) < max(2, int(max_fetch_per_state)):
            maryland_seed_limit = max(4, min(max(1, int(max_fetch_per_state)) * 3, 16))
            try:
                maryland_bootstrap_document_urls = await asyncio.wait_for(
                    _discover_maryland_rule_document_urls(
                        seed_urls=ordered_seed_urls[:8],
                        limit=maryland_seed_limit,
                    ),
                    timeout=20.0,
                )
            except Exception:
                maryland_bootstrap_document_urls = []
            for document_url in maryland_bootstrap_document_urls:
                candidate_urls.append(document_url)
            if maryland_bootstrap_document_urls:
                source_breakdown["maryland_comar_bootstrap"] = len(maryland_bootstrap_document_urls)

        if state_code == "ME" and not seeded_direct_detail_urls:
            maine_seed_limit = max(4, min(max(1, int(max_fetch_per_state)) * 4, 20))
            try:
                maine_bootstrap_document_urls = await asyncio.wait_for(
                    _discover_maine_rule_document_urls(
                        seed_urls=ordered_seed_urls[:8],
                        limit=maine_seed_limit,
                    ),
                    timeout=20.0,
                )
            except Exception:
                maine_bootstrap_document_urls = []
            for document_url in maine_bootstrap_document_urls:
                candidate_urls.append(document_url)
            if maine_bootstrap_document_urls:
                source_breakdown["maine_sos_rules_bootstrap"] = len(maine_bootstrap_document_urls)

        vermont_bootstrap_document_urls: List[str] = []
        if state_code == "VT" and len(seeded_direct_detail_urls) < max(2, int(max_fetch_per_state)):
            try:
                vermont_bootstrap_document_urls = await asyncio.wait_for(
                    _discover_vermont_rule_document_urls(
                        seed_urls=ordered_seed_urls[:8],
                        limit=min(max(max_fetch_per_state * 4, 8), 16),
                    ),
                    timeout=20.0,
                )
            except Exception:
                vermont_bootstrap_document_urls = []
            for document_url in vermont_bootstrap_document_urls:
                candidate_urls.append(document_url)
            if vermont_bootstrap_document_urls:
                source_breakdown["vermont_rss_bootstrap"] = len(vermont_bootstrap_document_urls)

        if state_code == "TN" and len(seeded_direct_detail_urls) < max(2, int(max_fetch_per_state)):
            try:
                tennessee_bootstrap_document_urls = await asyncio.wait_for(
                    _discover_tennessee_rule_document_urls(
                        seed_urls=ordered_seed_urls[:6],
                        limit=min(max(max_fetch_per_state * 4, 8), 16),
                    ),
                    timeout=25.0,
                )
            except Exception:
                tennessee_bootstrap_document_urls = []
            for document_url in tennessee_bootstrap_document_urls:
                candidate_urls.append(document_url)
            if tennessee_bootstrap_document_urls:
                source_breakdown["tennessee_sharetngov_bootstrap"] = len(tennessee_bootstrap_document_urls)

        hawaii_bootstrap_document_urls: List[str] = []
        if state_code == "HI" and not seeded_direct_detail_urls:
            try:
                hawaii_bootstrap_document_urls = await asyncio.wait_for(
                    _discover_hawaii_rule_document_urls(
                        seed_urls=ordered_seed_urls[:6],
                        limit=min(max(max_fetch_per_state * 4, 8), 16),
                    ),
                    timeout=25.0,
                )
            except Exception:
                hawaii_bootstrap_document_urls = []
            for document_url in hawaii_bootstrap_document_urls:
                candidate_urls.append(document_url)
            if hawaii_bootstrap_document_urls:
                source_breakdown["hawaii_official_pdf_bootstrap"] = len(hawaii_bootstrap_document_urls)

        louisiana_bootstrap_document_urls: List[str] = []
        if state_code == "LA" and not seeded_direct_detail_urls:
            try:
                louisiana_bootstrap_document_urls = await asyncio.wait_for(
                    _discover_louisiana_rule_document_urls(
                        seed_urls=ordered_seed_urls[:6],
                        limit=min(max(max_fetch_per_state * 4, 8), 16),
                    ),
                    timeout=25.0,
                )
            except Exception:
                louisiana_bootstrap_document_urls = []
            for document_url in louisiana_bootstrap_document_urls:
                candidate_urls.append(document_url)
            if louisiana_bootstrap_document_urls:
                source_breakdown["louisiana_official_pdf_bootstrap"] = len(louisiana_bootstrap_document_urls)

        rhode_island_bootstrap_document_urls: List[str] = []
        if state_code == "RI" and len(seeded_direct_detail_urls) < max(max(1, int(max_fetch_per_state)) * 2, 12):
            try:
                rhode_island_bootstrap_document_urls = await asyncio.wait_for(
                    _discover_rhode_island_rule_document_urls(
                        seed_urls=ordered_seed_urls[:6],
                        limit=min(max(max_fetch_per_state * 4, 12), 24),
                    ),
                    timeout=20.0,
                )
            except Exception:
                rhode_island_bootstrap_document_urls = []
            for document_url in rhode_island_bootstrap_document_urls:
                candidate_urls.append(document_url)
            if rhode_island_bootstrap_document_urls:
                source_breakdown["rhode_island_official_html_bootstrap"] = len(rhode_island_bootstrap_document_urls)

        iowa_bootstrap_document_urls: List[str] = []
        if state_code == "IA" and not seeded_direct_detail_urls:
            try:
                iowa_bootstrap_document_urls = await asyncio.wait_for(
                    _discover_iowa_rule_document_urls(
                        seed_urls=ordered_seed_urls[:6],
                        limit=min(max(max_fetch_per_state * 4, 8), 16),
                    ),
                    timeout=25.0,
                )
            except Exception:
                iowa_bootstrap_document_urls = []
            for document_url in iowa_bootstrap_document_urls:
                candidate_urls.append(document_url)
            if iowa_bootstrap_document_urls:
                source_breakdown["iowa_legislature_pdf_bootstrap"] = len(iowa_bootstrap_document_urls)

        alabama_bootstrap_document_urls: List[str] = []
        mississippi_bootstrap_document_urls: List[str] = []
        michigan_bootstrap_document_urls: List[str] = []
        alaska_bootstrap_document_urls: List[str] = []
        wyoming_bootstrap_document_urls: List[str] = []
        south_dakota_bootstrap_document_urls: List[str] = []
        montana_bootstrap_document_urls: List[str] = []
        california_bootstrap_document_urls: List[str] = []
        new_hampshire_bootstrap_document_urls: List[str] = []
        nebraska_bootstrap_document_urls: List[str] = []
        georgia_bootstrap_document_urls: List[str] = []
        kansas_bootstrap_document_urls: List[str] = []
        idaho_bootstrap_document_urls: List[str] = []
        if state_code == "AL" and not seeded_direct_detail_urls:
            try:
                alabama_bootstrap_document_urls = await asyncio.wait_for(
                    _discover_alabama_rule_document_urls(limit=min(max_fetch_per_state * 3, 32)),
                    timeout=25.0,
                )
            except Exception:
                alabama_bootstrap_document_urls = []
            for document_url in alabama_bootstrap_document_urls:
                candidate_urls.append(document_url)
            if alabama_bootstrap_document_urls:
                source_breakdown["alabama_public_code_bootstrap"] = len(alabama_bootstrap_document_urls)

        if state_code == "MS" and not seeded_direct_detail_urls:
            try:
                mississippi_bootstrap_document_urls = await asyncio.wait_for(
                    _discover_mississippi_rule_document_urls(limit=min(max_fetch_per_state * 3, 12)),
                    timeout=25.0,
                )
            except Exception:
                mississippi_bootstrap_document_urls = []
            for document_url in mississippi_bootstrap_document_urls:
                candidate_urls.append(document_url)
            if mississippi_bootstrap_document_urls:
                source_breakdown["mississippi_adminsearch_bootstrap"] = len(mississippi_bootstrap_document_urls)

        if state_code == "NE" and not seeded_direct_detail_urls:
            try:
                nebraska_bootstrap_document_urls = await asyncio.wait_for(
                    _discover_nebraska_rule_document_urls(limit=min(max(max_fetch_per_state * 4, 8), 20)),
                    timeout=25.0,
                )
            except Exception:
                nebraska_bootstrap_document_urls = []
            for document_url in nebraska_bootstrap_document_urls:
                candidate_urls.append(document_url)
            if nebraska_bootstrap_document_urls:
                source_breakdown["nebraska_rules_api_bootstrap"] = len(nebraska_bootstrap_document_urls)

        if state_code == "MI" and not seeded_direct_detail_urls:
            try:
                michigan_bootstrap_document_urls = await asyncio.wait_for(
                    _discover_michigan_rule_document_urls(
                        seed_urls=ordered_seed_urls[:6],
                        limit=min(max_fetch_per_state * 4, 16),
                    ),
                    timeout=25.0,
                )
            except Exception:
                michigan_bootstrap_document_urls = []
            for document_url in michigan_bootstrap_document_urls:
                candidate_urls.append(document_url)
            if michigan_bootstrap_document_urls:
                source_breakdown["michigan_admincode_bootstrap"] = len(michigan_bootstrap_document_urls)

        if state_code == "AK" and not seeded_direct_detail_urls:
            try:
                alaska_bootstrap_document_urls = await asyncio.wait_for(
                    _discover_alaska_rule_document_urls(
                        seed_urls=ordered_seed_urls[:6],
                            limit=min(max(1, int(max_fetch_per_state)) * 3, 20),
                    ),
                    timeout=25.0,
                )
            except Exception:
                alaska_bootstrap_document_urls = []
            for document_url in alaska_bootstrap_document_urls:
                candidate_urls.append(document_url)
            if alaska_bootstrap_document_urls:
                source_breakdown["alaska_print_view_bootstrap"] = len(alaska_bootstrap_document_urls)

        if state_code == "WY" and not seeded_direct_detail_urls:
            try:
                wyoming_bootstrap_document_urls = await asyncio.wait_for(
                    _discover_wyoming_rule_document_urls(
                        seed_urls=ordered_seed_urls[:6],
                        limit=min(max_fetch_per_state * 4, 16),
                    ),
                    timeout=25.0,
                )
            except Exception:
                wyoming_bootstrap_document_urls = []
            if not wyoming_bootstrap_document_urls:
                seen_wyoming_document_keys: set[str] = set()
                for seed_url in ordered_seed_urls[:4]:
                    if urlparse(seed_url).netloc.lower() != "rules.wyo.gov":
                        continue
                    try:
                        fetched = await asyncio.wait_for(
                            _run_blocking_fetch(
                                live_fetch_api.fetch,
                                UnifiedFetchRequest(
                                    url=seed_url,
                                    timeout_seconds=35,
                                    mode=OperationMode.BALANCED,
                                    domain="legal",
                                ),
                            ),
                            timeout=18.0,
                        )
                    except Exception:
                        continue
                    _record_rate_limit_metadata(fetched)
                    fetched_doc = getattr(fetched, "document", None)
                    fetched_html = str(getattr(fetched_doc, "html", "") or "")
                    program_urls = _candidate_wyoming_rule_urls_from_html(
                        html=fetched_html,
                        page_url=seed_url,
                        limit=max(12, min(48, max(1, int(max_fetch_per_state)) * 8)),
                    )
                    for program_url in program_urls[: max(4, min(8, int(max_fetch_per_state) * 2))]:
                        try:
                            program_scraped = await asyncio.wait_for(
                                _scrape_wyoming_rule_detail_via_ajax(program_url),
                                timeout=8.0,
                            )
                        except Exception:
                            program_scraped = None
                        if program_scraped is None:
                            continue
                        program_html = str(getattr(program_scraped, "html", "") or "")
                        for viewer_url in _candidate_wyoming_rule_urls_from_html(
                            html=program_html,
                            page_url=program_url,
                            limit=max(12, min(48, max(1, int(max_fetch_per_state)) * 8)),
                        ):
                            viewer_key = _url_key(viewer_url)
                            if not viewer_key or viewer_key in seen_wyoming_document_keys:
                                continue
                            seen_wyoming_document_keys.add(viewer_key)
                            wyoming_bootstrap_document_urls.append(viewer_url)
                            if len(wyoming_bootstrap_document_urls) >= min(max_fetch_per_state * 4, 16):
                                break
                        if len(wyoming_bootstrap_document_urls) >= min(max_fetch_per_state * 4, 16):
                            break
                    if wyoming_bootstrap_document_urls:
                        break
            for document_url in wyoming_bootstrap_document_urls:
                candidate_urls.append(document_url)
            if wyoming_bootstrap_document_urls:
                source_breakdown["wyoming_ajax_bootstrap"] = len(wyoming_bootstrap_document_urls)

        if state_code == "SD":
            try:
                south_dakota_bootstrap_document_urls = await asyncio.wait_for(
                    _discover_south_dakota_rule_document_urls(limit=min(max(max_fetch_per_state * 4, 8), 16)),
                    timeout=25.0,
                )
            except Exception:
                south_dakota_bootstrap_document_urls = []
            for document_url in south_dakota_bootstrap_document_urls:
                candidate_urls.append(document_url)
            if south_dakota_bootstrap_document_urls:
                source_breakdown["south_dakota_rules_api_bootstrap"] = len(south_dakota_bootstrap_document_urls)

        if state_code == "MT" and not seeded_direct_detail_urls:
            montana_seed_limit = max(2, min(max(1, int(max_fetch_per_state)) * 3, int(max_candidates_per_state), 12))
            seen_montana_document_keys: set[str] = set()
            for seed_url in ordered_seed_urls[:8]:
                if not _montana_collection_uuid_from_url(seed_url):
                    continue
                try:
                    montana_document_urls = await asyncio.wait_for(
                        _discover_montana_rule_document_urls(
                            seed_url,
                            limit=max(1, montana_seed_limit - len(montana_bootstrap_document_urls)),
                        ),
                        timeout=20.0,
                    )
                except Exception:
                    montana_document_urls = []
                for document_url in montana_document_urls:
                    document_key = _url_key(document_url)
                    if not document_key or document_key in seen_montana_document_keys:
                        continue
                    seen_montana_document_keys.add(document_key)
                    montana_bootstrap_document_urls.append(document_url)
                    candidate_urls.append(document_url)
                    if len(montana_bootstrap_document_urls) >= montana_seed_limit:
                        break
                if len(montana_bootstrap_document_urls) >= montana_seed_limit:
                    break
            if montana_bootstrap_document_urls:
                source_breakdown["montana_public_api_bootstrap"] = len(montana_bootstrap_document_urls)

        if state_code == "CO" and not seeded_direct_detail_urls:
            colorado_bootstrap_limit = min(max(1, int(max_fetch_per_state)), 8)
            try:
                from ..web_archiving.unified_web_scraper import (
                    ScraperConfig as _ScraperConfig,
                    ScraperMethod as _ScraperMethod,
                    UnifiedWebScraper as _UnifiedWebScraper,
                )
            except Exception:
                try:
                    from ipfs_datasets_py.processors.web_archiving.unified_web_scraper import (  # type: ignore[no-redef]
                        ScraperConfig as _ScraperConfig,
                        ScraperMethod as _ScraperMethod,
                        UnifiedWebScraper as _UnifiedWebScraper,
                    )
                except Exception:
                    _ScraperConfig = None  # type: ignore[assignment]
                    _ScraperMethod = None  # type: ignore[assignment]
                    _UnifiedWebScraper = None  # type: ignore[assignment]

            if _UnifiedWebScraper is not None and _ScraperConfig is not None and _ScraperMethod is not None:
                colorado_bootstrap_scraper = _UnifiedWebScraper(
                    _ScraperConfig(
                        timeout=20,
                        max_retries=1,
                        extract_links=True,
                        extract_text=True,
                        fallback_enabled=False,
                        preferred_methods=[_ScraperMethod.REQUESTS_ONLY],
                    )
                )
            else:
                colorado_bootstrap_scraper = live_scraper

            colorado_bootstrap_document_urls = await _discover_colorado_rule_document_urls(
                seed_urls=ordered_seed_urls,
                live_scraper=colorado_bootstrap_scraper,
                allowed_hosts=allowed_hosts,
                limit=colorado_bootstrap_limit,
            )
            _record_co_progress(
                "bootstrap_done",
                discovered=len(colorado_bootstrap_document_urls),
                limit=colorado_bootstrap_limit,
            )
            for document_url in colorado_bootstrap_document_urls:
                candidate_urls.append(document_url)
            if colorado_bootstrap_document_urls:
                source_breakdown["colorado_ccr_bootstrap"] = len(colorado_bootstrap_document_urls)

        if state_code == "CT" and not seeded_direct_detail_urls:
            connecticut_bootstrap_limit = min(max(1, int(max_fetch_per_state)), 8)
            try:
                from ..web_archiving.unified_web_scraper import (
                    ScraperConfig as _ScraperConfig,
                    ScraperMethod as _ScraperMethod,
                    UnifiedWebScraper as _UnifiedWebScraper,
                )
            except Exception:
                try:
                    from ipfs_datasets_py.processors.web_archiving.unified_web_scraper import (  # type: ignore[no-redef]
                        ScraperConfig as _ScraperConfig,
                        ScraperMethod as _ScraperMethod,
                        UnifiedWebScraper as _UnifiedWebScraper,
                    )
                except Exception:
                    _ScraperConfig = None  # type: ignore[assignment]
                    _ScraperMethod = None  # type: ignore[assignment]
                    _UnifiedWebScraper = None  # type: ignore[assignment]

            if _UnifiedWebScraper is not None and _ScraperConfig is not None and _ScraperMethod is not None:
                connecticut_bootstrap_scraper = _UnifiedWebScraper(
                    _ScraperConfig(
                        timeout=20,
                        max_retries=1,
                        extract_links=True,
                        extract_text=True,
                        fallback_enabled=False,
                        preferred_methods=[_ScraperMethod.REQUESTS_ONLY],
                    )
                )
            else:
                connecticut_bootstrap_scraper = live_scraper

            connecticut_bootstrap_document_urls = await _discover_connecticut_rule_document_urls(
                seed_urls=ordered_seed_urls,
                live_scraper=connecticut_bootstrap_scraper,
                allowed_hosts=allowed_hosts,
                limit=connecticut_bootstrap_limit,
            )
            for document_url in connecticut_bootstrap_document_urls:
                candidate_urls.append(document_url)
            if connecticut_bootstrap_document_urls:
                source_breakdown["connecticut_eregulations_bootstrap"] = len(connecticut_bootstrap_document_urls)

        if state_code == "CA" and not seeded_direct_detail_urls:
            california_bootstrap_limit = min(max(1, int(max_fetch_per_state)), 8)
            try:
                from ..web_archiving.unified_api import UnifiedWebArchivingAPI as _UnifiedWebArchivingAPI
                from ..web_archiving.unified_web_scraper import (
                    ScraperConfig as _ScraperConfig,
                    ScraperMethod as _ScraperMethod,
                    UnifiedWebScraper as _UnifiedWebScraper,
                )
            except Exception:
                try:
                    from ipfs_datasets_py.processors.web_archiving.unified_api import UnifiedWebArchivingAPI as _UnifiedWebArchivingAPI  # type: ignore[no-redef]
                    from ipfs_datasets_py.processors.web_archiving.unified_web_scraper import (  # type: ignore[no-redef]
                        ScraperConfig as _ScraperConfig,
                        ScraperMethod as _ScraperMethod,
                        UnifiedWebScraper as _UnifiedWebScraper,
                    )
                except Exception:
                    _UnifiedWebArchivingAPI = None  # type: ignore[assignment]
                    _ScraperConfig = None  # type: ignore[assignment]
                    _ScraperMethod = None  # type: ignore[assignment]
                    _UnifiedWebScraper = None  # type: ignore[assignment]

            if (
                _UnifiedWebArchivingAPI is not None
                and _ScraperConfig is not None
                and _ScraperMethod is not None
                and _UnifiedWebScraper is not None
            ):
                california_bootstrap_cfg = _ScraperConfig(
                    timeout=20,
                    max_retries=1,
                    extract_links=True,
                    extract_text=True,
                    fallback_enabled=False,
                    preferred_methods=[_ScraperMethod.REQUESTS_ONLY],
                )
                california_bootstrap_document_urls = await _discover_california_westlaw_document_urls(
                    seed_urls=ordered_seed_urls,
                    live_scraper=_UnifiedWebScraper(california_bootstrap_cfg),
                    live_fetch_api=_UnifiedWebArchivingAPI(scraper=_UnifiedWebScraper(california_bootstrap_cfg)),
                    direct_fetch_api=direct_fetch_api,
                    allowed_hosts=allowed_hosts,
                    limit=california_bootstrap_limit,
                )
            else:
                california_bootstrap_document_urls = await _discover_california_westlaw_document_urls(
                    seed_urls=ordered_seed_urls,
                    live_scraper=live_scraper,
                    live_fetch_api=live_fetch_api,
                    direct_fetch_api=direct_fetch_api,
                    allowed_hosts=allowed_hosts,
                    limit=california_bootstrap_limit,
                )
            for document_url in california_bootstrap_document_urls:
                candidate_urls.append(document_url)
            if california_bootstrap_document_urls:
                source_breakdown["california_westlaw_document_bootstrap"] = len(california_bootstrap_document_urls)

        if state_code == "NH":
            nh_seed_limit = min(max(1, int(max_fetch_per_state)) * 2, 8)
            try:
                new_hampshire_bootstrap_result = await asyncio.wait_for(
                    _discover_new_hampshire_archived_rule_document_urls_with_diagnostics(
                        seed_urls=ordered_seed_urls,
                        allowed_hosts=allowed_hosts,
                        limit=nh_seed_limit,
                    ),
                    timeout=25.0,
                )
            except Exception:
                new_hampshire_bootstrap_document_urls = []
                new_hampshire_bootstrap_diagnostics = {"error": "bootstrap_failed"}
            else:
                new_hampshire_bootstrap_document_urls = list(new_hampshire_bootstrap_result.get("document_urls") or [])
                new_hampshire_bootstrap_diagnostics = dict(new_hampshire_bootstrap_result.get("diagnostics") or {})
            for document_url in new_hampshire_bootstrap_document_urls:
                candidate_urls.append(document_url)
            if new_hampshire_bootstrap_document_urls:
                source_breakdown["new_hampshire_archive_bootstrap"] = len(new_hampshire_bootstrap_document_urls)

        if state_code == "GA" and not seeded_direct_detail_urls:
            try:
                georgia_bootstrap_document_urls = await asyncio.wait_for(
                    _discover_georgia_rule_document_urls(
                        seed_urls=ordered_seed_urls,
                        limit=max_fetch_per_state,
                    ),
                    timeout=20.0,
                )
            except Exception:
                georgia_bootstrap_document_urls = []
            for document_url in georgia_bootstrap_document_urls:
                candidate_urls.append(document_url)
            if georgia_bootstrap_document_urls:
                source_breakdown["georgia_gac_bootstrap"] = len(georgia_bootstrap_document_urls)

        if state_code == "KS" and not seeded_direct_detail_urls:
            try:
                kansas_bootstrap_document_urls = await asyncio.wait_for(
                    _discover_kansas_rule_document_urls(
                        seed_urls=ordered_seed_urls,
                        live_scraper=live_scraper,
                        limit=min(max(max_fetch_per_state * 4, 8), 16),
                    ),
                    timeout=25.0,
                )
            except Exception:
                kansas_bootstrap_document_urls = []
            for document_url in kansas_bootstrap_document_urls:
                candidate_urls.append(document_url)
            if kansas_bootstrap_document_urls:
                source_breakdown["kansas_kar_bootstrap"] = len(kansas_bootstrap_document_urls)

        if state_code == "ID" and not seeded_direct_detail_urls:
            try:
                idaho_bootstrap_document_urls = await asyncio.wait_for(
                    _discover_idaho_rule_document_urls(
                        seed_urls=ordered_seed_urls,
                        live_scraper=live_scraper,
                        limit=min(max(max_fetch_per_state * 4, 8), 24),
                    ),
                    timeout=20.0,
                )
            except Exception:
                idaho_bootstrap_document_urls = []
            for document_url in idaho_bootstrap_document_urls:
                candidate_urls.append(document_url)
            if idaho_bootstrap_document_urls:
                source_breakdown["idaho_current_rules_pdf_bootstrap"] = len(idaho_bootstrap_document_urls)

        direct_detail_ready = bool(
            alabama_bootstrap_document_urls
            or hawaii_bootstrap_document_urls
            or iowa_bootstrap_document_urls
            or louisiana_bootstrap_document_urls
            or vermont_bootstrap_document_urls
            or michigan_bootstrap_document_urls
            or alaska_bootstrap_document_urls
            or wyoming_bootstrap_document_urls
            or south_dakota_bootstrap_document_urls
            or utah_api_rule_urls
            or arizona_bootstrap_document_urls
            or arkansas_bootstrap_document_urls
            or texas_bootstrap_document_urls
            or oklahoma_bootstrap_document_urls
            or tennessee_bootstrap_document_urls
            or seeded_direct_detail_urls
            or montana_bootstrap_document_urls
            or california_bootstrap_document_urls
            or new_hampshire_bootstrap_document_urls
            or georgia_bootstrap_document_urls
            or kansas_bootstrap_document_urls
            or idaho_bootstrap_document_urls
        ) or _direct_detail_candidate_backlog_is_ready(
            candidate_urls,
            max_fetch=max_fetch_per_state,
        )

        # Curated seeds often already expose substantive rule pages or article/part
        # links. Prefetch them before broad agentic discovery so states like Indiana
        # and Rhode Island can short-circuit expensive exploration when the official
        # entrypoints are already sufficient.
        preseed_signal = direct_detail_ready
        if not direct_detail_ready:
            for seed_url in ordered_seed_urls[:6]:
                remaining_budget_s = max(0.0, presearch_budget_deadline - time.monotonic())
                if remaining_budget_s <= 1.0:
                    break
                host = urlparse(seed_url).netloc
                fetch_api = live_fetch_api if _prefers_live_fetch(seed_url) else direct_fetch_api
                try:
                    fetched = await asyncio.wait_for(
                        _run_blocking_fetch(
                            fetch_api.fetch,
                            UnifiedFetchRequest(
                                url=seed_url,
                                timeout_seconds=35,
                                mode=OperationMode.BALANCED,
                                domain=".gov" if host.endswith(".gov") else "legal",
                            ),
                        ),
                        timeout=max(1.0, min(12.0, remaining_budget_s)),
                    )
                    _record_rate_limit_metadata(fetched)
                    fetched_doc = getattr(fetched, "document", None)
                    fetched_text = str(getattr(fetched_doc, "text", "") or "").strip()
                    fetched_title = str(getattr(fetched_doc, "title", "") or "").strip()
                    fetched_html = str(getattr(fetched_doc, "html", "") or "")
                    fetched_title, fetched_text = await _normalize_candidate_document_content(
                        url=seed_url,
                        title=fetched_title,
                        text=fetched_text,
                    )
                    seed_is_substantive = _is_substantive_rule_text(
                        text=fetched_text,
                        title=fetched_title,
                        url=seed_url,
                        min_chars=min_full_text_chars,
                    )
                    seed_is_relaxed = relaxed_recovery and _is_relaxed_recovery_text(
                        text=fetched_text,
                        title=fetched_title,
                        url=seed_url,
                    )
                    inventory_seed = _looks_like_rule_inventory_page(
                        text=fetched_text,
                        title=fetched_title,
                        url=seed_url,
                    )

                    if inventory_seed:
                        preseed_signal = True
                        source_breakdown["seed_prefetch"] = int(source_breakdown.get("seed_prefetch", 0)) + 1
                        if state_code == "VT":
                            # Vermont's public SOS/ICAR pages are discovery/inventory surfaces,
                            # not substantive rule text. Once we've confirmed that shape, stop
                            # expanding them so bounded runs do not spend the full state budget.
                            break
                        for rule_url in _candidate_montana_rule_urls_from_text(
                            text=fetched_text,
                            url=seed_url,
                            limit=24,
                        ):
                            candidate_urls.append(rule_url)
                        for link_url in _candidate_links_from_html(
                            fetched_html,
                            base_host=host,
                            page_url=seed_url,
                            limit=24,
                            allowed_hosts=allowed_hosts,
                        ):
                            if _score_candidate_url(link_url) > 0:
                                candidate_urls.append(link_url)
                        for rule_url in _candidate_utah_rule_urls_from_public_api(
                            url=seed_url,
                            limit=24,
                        ):
                            candidate_urls.append(rule_url)
                        if state_code == "MT":
                            try:
                                montana_rule_urls = await asyncio.wait_for(
                                    _discover_montana_rule_document_urls(seed_url, limit=24),
                                    timeout=20.0,
                                )
                            except Exception:
                                montana_rule_urls = []
                            for rule_rank, rule_url in enumerate(montana_rule_urls):
                                if rule_url not in candidate_urls:
                                    candidate_urls.append(rule_url)
                                seed_expansion_candidates.append(
                                    (rule_url, _score_candidate_url(rule_url) + 4 + max(0, 4 - int(rule_rank)))
                                )
                        if (
                            state_code == "WY"
                            and not wyoming_bootstrap_document_urls
                            and urlparse(seed_url).netloc.lower() == "rules.wyo.gov"
                        ):
                            wy_program_urls = _candidate_wyoming_rule_urls_from_html(
                                html=fetched_html,
                                page_url=seed_url,
                                limit=max(12, min(48, max(1, int(max_fetch_per_state)) * 8)),
                            )
                            for program_rank, program_url in enumerate(wy_program_urls[: max(4, min(8, int(max_fetch_per_state) * 2))]):
                                try:
                                    program_scraped = await asyncio.wait_for(
                                        _scrape_wyoming_rule_detail_via_ajax(program_url),
                                        timeout=8.0,
                                    )
                                except Exception:
                                    program_scraped = None
                                if program_scraped is None:
                                    candidate_urls.append(program_url)
                                    seed_expansion_candidates.append(
                                        (program_url, _score_candidate_url(program_url) + 8 + max(0, 4 - int(program_rank)))
                                    )
                                    continue
                                program_html = str(getattr(program_scraped, "html", "") or "")
                                viewer_urls = _candidate_wyoming_rule_urls_from_html(
                                    html=program_html,
                                    page_url=program_url,
                                    limit=max(12, min(48, max(1, int(max_fetch_per_state)) * 8)),
                                )
                                if not viewer_urls:
                                    candidate_urls.append(program_url)
                                    seed_expansion_candidates.append(
                                        (program_url, _score_candidate_url(program_url) + 8 + max(0, 4 - int(program_rank)))
                                    )
                                    continue
                                for viewer_rank, viewer_url in enumerate(viewer_urls):
                                    if viewer_url not in candidate_urls:
                                        candidate_urls.append(viewer_url)
                                    seed_expansion_candidates.append(
                                        (viewer_url, _score_candidate_url(viewer_url) + 12 + max(0, 6 - int(viewer_rank)))
                                    )
                                    source_breakdown["wyoming_ajax_bootstrap"] = int(
                                        source_breakdown.get("wyoming_ajax_bootstrap", 0)
                                    ) + 1
                        break

                    if seed_is_substantive or seed_is_relaxed:
                        preseed_signal = True
                        seed_key = _url_key(seed_url)
                        if seed_key:
                            preseed_substantive_url_keys.add(seed_key)
                        source_breakdown["seed_prefetch"] = int(source_breakdown.get("seed_prefetch", 0)) + 1
                        break
                except Exception:
                    pass

        if not direct_detail_ready:
            direct_detail_ready = _direct_detail_candidate_backlog_is_ready(
                candidate_urls,
                max_fetch=max_fetch_per_state,
            )

        if not preseed_signal:
            remaining_budget_s = max(0.0, presearch_budget_deadline - time.monotonic())
            try:
                if remaining_budget_s > 0.0:
                    archive_results = await asyncio.wait_for(
                        legal_archive._search_archives_multi_domain(
                            query=query,
                            domains=_agentic_domains_for_state(state_code),
                            max_results_per_domain=max(1, int(max_results_per_domain)),
                        ),
                        timeout=max(0.01, min(archive_search_timeout_seconds, remaining_budget_s)),
                    )
                else:
                    archive_results = {"results": []}
                for row in (archive_results or {}).get("results", []) or []:
                    if not isinstance(row, dict):
                        continue
                    url = str(row.get("url") or "").strip()
                    if not url or _NON_ADMIN_SOURCE_URL_RE.search(url) or not _url_allowed_for_state(url, allowed_hosts):
                        continue
                    candidate_urls.append(url)
                    source_breakdown["archives"] = int(source_breakdown.get("archives", 0)) + 1
            except Exception:
                pass

            remaining_budget_s = max(0.0, presearch_budget_deadline - time.monotonic())
            try:
                if remaining_budget_s > 0.0:
                    unified_search = await asyncio.wait_for(
                        asyncio.to_thread(
                            unified_api.search,
                            UnifiedSearchRequest(
                                query=query,
                                max_results=max(5, int(max_candidates_per_state)),
                                mode=OperationMode.BALANCED,
                                domain="legal",
                            ),
                        ),
                        timeout=max(0.01, min(40.0, remaining_budget_s)),
                    )
                else:
                    unified_search = SimpleNamespace(results=[])
                for hit in getattr(unified_search, "results", []) or []:
                    url = str(getattr(hit, "url", "") or "").strip()
                    if not url or _NON_ADMIN_SOURCE_URL_RE.search(url) or not _url_allowed_for_state(url, allowed_hosts):
                        continue
                    candidate_urls.append(url)
                    source_breakdown["search"] = int(source_breakdown.get("search", 0)) + 1
            except Exception:
                pass

        discovered: Dict[str, Any] = {}
        if not preseed_signal:
            remaining_budget_s = max(0.0, presearch_budget_deadline - time.monotonic())
            try:
                if remaining_budget_s > 0.0:
                    discovered = await asyncio.wait_for(
                        asyncio.to_thread(
                            lambda: unified_api.agentic_discover_and_fetch(
                                seed_urls=seed_urls,
                                target_terms=_query_target_terms_for_state(state_code),
                                max_hops=max(0, int(max_hops)),
                                max_pages=max(1, int(max_pages)),
                                mode=OperationMode.BALANCED,
                                allowed_hosts=sorted(allowed_hosts),
                                blocked_url_patterns=[_NON_ADMIN_SOURCE_URL_RE.pattern],
                            ),
                        ),
                        timeout=max(0.01, min(70.0, remaining_budget_s)),
                    )
                _record_rate_limit_metadata(discovered)
                for fetch_row in discovered.get("results", []) or []:
                    if not isinstance(fetch_row, dict):
                        continue
                    _record_rate_limit_metadata(fetch_row)
                    document = fetch_row.get("document") or {}
                    if isinstance(document, dict):
                        url = str(document.get("url") or fetch_row.get("url") or "").strip()
                    else:
                        url = str(fetch_row.get("url") or "").strip()
                    if not url or _NON_ADMIN_SOURCE_URL_RE.search(url) or not _url_allowed_for_state(url, allowed_hosts):
                        continue
                    candidate_urls.append(url)
                    source_breakdown["agentic_discovery"] = int(source_breakdown.get("agentic_discovery", 0)) + 1
            except Exception:
                pass

        ranked_urls = sorted(
            {
                str(url).strip(): _score_candidate_url(url)
                for url in candidate_urls
                if str(url or "").strip().startswith(("http://", "https://"))
                and _url_allowed_for_state(str(url).strip(), allowed_hosts)
            }.items(),
            key=lambda item: item[1],
            reverse=True,
        )

        if state_code == "AL" and alabama_bootstrap_document_urls:
            ranked_urls = [
                (url, score)
                for url, score in ranked_urls
                if urlparse(url).netloc.lower() == "admincode.legislature.state.al.us"
            ]

        if state_code == "AR" and arkansas_bootstrap_document_urls:
            arkansas_official_ranked_urls = [
                (url, score)
                for url, score in ranked_urls
                if urlparse(url).netloc.lower()
                in {
                    "codeofarrules.arkansas.gov",
                    "sos-rules-reg.ark.org",
                    "sos.arkansas.gov",
                    "www.sos.arkansas.gov",
                }
            ]
            if arkansas_official_ranked_urls:
                ranked_urls = arkansas_official_ranked_urls

        if state_code == "VT" and not direct_detail_ready:
            ranked_urls = []

        statutes: List[Dict[str, Any]] = []
        direct_doc_urls: set[str] = set()
        az_official_document_group_keys: set[str] = set()
        az_official_document_doc_keys_by_group: Dict[str, str] = {}
        statute_index_by_doc_key: Dict[str, int] = {}
        kg_row_index_by_doc_key: Dict[str, int] = {}
        seed_expansion_candidates: List[tuple[str, int]] = []
        rules_by_host: Dict[str, int] = defaultdict(int)
        format_counts: Dict[str, int] = {"html": 0, "pdf": 0, "rtf": 0}
        visited_hosts: set[str] = set()
        parallel_prefetch_attempted = 0
        parallel_prefetch_succeeded = 0
        parallel_prefetch_rule_hits = 0
        expanded_urls = 0
        inspected_urls = 0
        max_fetch = max(1, int(max_fetch_per_state))
        min_text_chars = max(140, int(min_full_text_chars // 2))
        if require_substantive_text:
            min_text_chars = max(220, int(min_full_text_chars))
        effective_fetch_concurrency = max(1, int(fetch_concurrency))
        preloop_budget_deadline = (
            math.inf
            if state_budget_is_unbounded
            else state_start + max(12.0, min(45.0, per_state_budget_s * 0.25))
        )
        if (
            not state_budget_is_unbounded
            and
            state_code == "AZ"
            and any(
                _is_immediate_direct_detail_candidate_url(seed_url) and _is_pdf_candidate_url(seed_url)
                for seed_url in ordered_seed_urls[:8]
            )
            and not any(
                _is_immediate_direct_detail_candidate_url(seed_url) and _is_rtf_candidate_url(seed_url)
                for seed_url in ordered_seed_urls[:8]
            )
        ):
            preloop_budget_deadline = max(
                preloop_budget_deadline,
                state_start + max(30.0, min(90.0, per_state_budget_s - 0.5)),
            )
        if state_code == "AZ" and not state_budget_is_unbounded:
            preloop_budget_deadline = max(
                preloop_budget_deadline,
                state_start + max(90.0, min(180.0, per_state_budget_s - 0.5)),
            )
        if state_code == "CA" and not state_budget_is_unbounded:
            preloop_budget_deadline = max(
                preloop_budget_deadline,
                state_start + max(45.0, min(70.0, per_state_budget_s - 0.5)),
            )

        async def _append_document_if_rule(
            doc_url: str,
            doc_title: str,
            doc_text: str,
            method_value: Any = None,
            *,
            source_phase: str = "",
        ) -> bool:
            doc_title, doc_text = await _normalize_candidate_document_content(
                url=doc_url,
                title=doc_title,
                text=doc_text,
            )
            method_value = getattr(method_value, "value", method_value)
            if not doc_url.startswith(("http://", "https://")):
                return False
            if not _url_allowed_for_state(doc_url, allowed_hosts):
                return False
            is_substantive = _is_substantive_rule_text(
                text=doc_text,
                title=doc_title,
                url=doc_url,
                min_chars=min_text_chars,
            )
            if not is_substantive:
                if not (relaxed_recovery and _is_relaxed_recovery_text(text=doc_text, title=doc_title, url=doc_url)):
                    return False
                if not _should_emit_relaxed_recovery_statute(text=doc_text, title=doc_title, url=doc_url):
                    return False
            doc_key = _url_key(doc_url)
            az_group_key = _arizona_official_document_group_key(doc_url) if state_code == "AZ" else ""
            doc_format = _document_format_for_url(doc_url)
            if doc_key in direct_doc_urls:
                return False
            if az_group_key and az_group_key in az_official_document_group_keys:
                existing_doc_key = az_official_document_doc_keys_by_group.get(az_group_key, "")
                if not _should_prefer_arizona_official_document_url(doc_url, existing_doc_key):
                    return False
                statute_index = statute_index_by_doc_key.get(existing_doc_key)
                kg_row_index = kg_row_index_by_doc_key.get(existing_doc_key)
                if statute_index is None or kg_row_index is None:
                    return False

                existing_statute = statutes[statute_index]
                existing_doc_format = _document_format_for_url(existing_doc_key)
                existing_section_name = str(existing_statute.get("section_name") or "").strip()
                stored_section_name = doc_title or f"{state_name} Administrative Rules (agentic source {statute_index + 1})"
                if _looks_like_bad_rtf_title(stored_section_name) and existing_section_name and not _looks_like_bad_rtf_title(existing_section_name):
                    stored_section_name = existing_section_name
                stored_text = doc_text.strip() or f"{stored_section_name}\nAdministrative rules source URL: {doc_url}"

                direct_doc_urls.discard(existing_doc_key)
                direct_doc_urls.add(doc_key)
                az_official_document_doc_keys_by_group[az_group_key] = doc_key
                statute_index_by_doc_key.pop(existing_doc_key, None)
                statute_index_by_doc_key[doc_key] = statute_index
                kg_row_index_by_doc_key.pop(existing_doc_key, None)
                kg_row_index_by_doc_key[doc_key] = kg_row_index
                if existing_doc_format != doc_format:
                    format_counts[existing_doc_format] = max(0, int(format_counts.get(existing_doc_format, 0)) - 1)
                    format_counts[doc_format] = int(format_counts.get(doc_format, 0)) + 1

                existing_statute["section_name"] = stored_section_name
                existing_statute["short_title"] = stored_section_name
                existing_statute["full_text"] = stored_text
                existing_statute["summary"] = stored_text[:500]
                existing_statute["source_url"] = doc_url
                structured_data = existing_statute.get("structured_data") or {}
                if not isinstance(structured_data, dict):
                    structured_data = {}
                structured_data.update(
                    {
                        "type": "regulation",
                        "agentic_discovery": True,
                        "relaxed_recovery": bool(relaxed_recovery),
                        "method_used": method_value,
                        "source_domain": urlparse(doc_url).netloc,
                    }
                )
                existing_statute["structured_data"] = structured_data

                kg_rows[kg_row_index] = {
                    **kg_rows[kg_row_index],
                    "url": doc_url,
                    "domain": urlparse(doc_url).netloc,
                    "title": stored_section_name,
                    "text": doc_text,
                    "method_used": method_value,
                    "query": query,
                    "source": "agentic_web_archiving",
                    "fetched_at": datetime.now().isoformat(),
                }
                return True
            direct_doc_urls.add(doc_key)
            if az_group_key:
                az_official_document_group_keys.add(az_group_key)
                az_official_document_doc_keys_by_group[az_group_key] = doc_key
            host_value = urlparse(doc_url).netloc.lower()
            if host_value:
                visited_hosts.add(host_value)
                rules_by_host[host_value] += 1
            format_counts[doc_format] = int(format_counts.get(doc_format, 0)) + 1

            section_number = f"A{len(statutes) + 1}"
            section_name = doc_title or f"{state_name} Administrative Rules (agentic source {len(statutes) + 1})"
            stored_text = doc_text.strip() or f"{section_name}\nAdministrative rules source URL: {doc_url}"
            statute = {
                "state_code": state_code,
                "state_name": state_name,
                "statute_id": f"{state_code}-AGENTIC-{section_number}",
                "code_name": f"{state_name} Administrative Rules (Agentic Discovery)",
                "section_number": section_number,
                "section_name": section_name,
                "short_title": section_name,
                "full_text": stored_text,
                "summary": stored_text[:500],
                "legal_area": "administrative",
                "source_url": doc_url,
                "official_cite": f"{state_code} Admin Rule {section_number}",
                "structured_data": {
                    "type": "regulation",
                    "agentic_discovery": True,
                    "relaxed_recovery": bool(relaxed_recovery),
                    "method_used": method_value,
                    "source_domain": urlparse(doc_url).netloc,
                },
            }
            statutes.append(statute)
            statute_index_by_doc_key[doc_key] = len(statutes) - 1
            kg_rows.append(
                {
                    "state_code": state_code,
                    "state_name": state_name,
                    "url": doc_url,
                    "domain": urlparse(doc_url).netloc,
                    "title": doc_title,
                    "text": doc_text,
                    "method_used": method_value,
                    "query": query,
                    "source": "agentic_web_archiving",
                    "fetched_at": datetime.now().isoformat(),
                }
            )
            kg_row_index_by_doc_key[doc_key] = len(kg_rows) - 1
            if state_code == "AZ":
                _mark_az_emitted_document(
                    doc_url,
                    source_phase=source_phase or "pending_candidate",
                    title=section_name,
                    method_value=method_value,
                )
            if co_progress_enabled:
                accepted_count = len(statutes)
                if accepted_count <= 5 or accepted_count % 25 == 0:
                    _record_co_progress(
                        "accepted_rule",
                        accepted=accepted_count,
                        source_phase=source_phase or "pending_candidate",
                        url=doc_url,
                    )
            return True

        prefetch_candidates: List[str] = []
        if not direct_detail_ready:
            prefetch_candidates = [
                url
                for url, score in ranked_urls
                if int(score) > 0
                and not _NON_ADMIN_SOURCE_URL_RE.search(str(url))
                and _url_key(url) not in direct_doc_urls
                and _url_key(url) not in preseed_substantive_url_keys
            ][: max(2, min(max_candidates_per_state, max_fetch * 3, effective_fetch_concurrency * 4))]

        if prefetch_candidates and time.monotonic() < preloop_budget_deadline:
            parallel_prefetch_attempted = len(prefetch_candidates)
            try:
                archived_results = await asyncio.wait_for(
                    parallel_archiver.archive_urls_parallel(
                        prefetch_candidates,
                        jurisdiction="state",
                        state_code=state_code,
                    ),
                    timeout=min(35.0, 8.0 + float(len(prefetch_candidates)) * 2.0),
                )
            except Exception:
                archived_results = []

            for archived in archived_results:
                if len(statutes) >= max_fetch:
                    break
                if not getattr(archived, "success", False):
                    continue
                archived_url = str(getattr(archived, "url", "") or "").strip()
                archived_content = str(getattr(archived, "content", "") or "").strip()
                archived_source = str(getattr(archived, "source", "") or "parallel_archive")
                if not archived_url or not archived_content:
                    continue
                parallel_prefetch_succeeded += 1
                source_breakdown["parallel_archive_prefetch"] = int(source_breakdown.get("parallel_archive_prefetch", 0)) + 1
                archived_title = _title_from_extracted_pdf_text(text=archived_content, url=archived_url)
                accepted_prefetch = await _append_document_if_rule(
                    archived_url,
                    archived_title,
                    archived_content,
                    archived_source,
                    source_phase="parallel_prefetch",
                )
                if accepted_prefetch:
                    parallel_prefetch_rule_hits += 1
                if not accepted_prefetch and _looks_like_rule_inventory_page(text=archived_content, title=archived_title, url=archived_url):
                    archived_host = urlparse(archived_url).netloc
                    for link_url in _candidate_links_from_html(
                        archived_content,
                        base_host=archived_host,
                        page_url=archived_url,
                        limit=16,
                        allowed_hosts=allowed_hosts,
                    ):
                        link_score = _score_candidate_url(link_url)
                        if link_score <= 0:
                            continue
                        if link_url not in candidate_urls:
                            candidate_urls.append(link_url)
                        seed_expansion_candidates.append((link_url, link_score + 1))
                        expanded_urls += 1

        prioritized_seed_document_urls: List[str] = []
        seen_seed_document_keys: set[str] = set()
        seed_document_limit = min(max(max_fetch * 3, max_fetch + 2), 12)
        for seed_url in ordered_seed_urls:
            if not _is_immediate_direct_detail_candidate_url(seed_url):
                continue
            seed_candidates = [seed_url]
            for candidate_url in seed_candidates:
                doc_key = _url_key(candidate_url)
                if not doc_key or doc_key in seen_seed_document_keys:
                    continue
                seen_seed_document_keys.add(doc_key)
                prioritized_seed_document_urls.append(candidate_url)
                if len(prioritized_seed_document_urls) >= seed_document_limit:
                    break
            if len(prioritized_seed_document_urls) >= seed_document_limit:
                break

        if state_code == "AZ":
            prioritized_seed_document_urls = _prioritize_arizona_seed_document_urls(
                prioritized_seed_document_urls,
                limit=6,
            )
        else:
            prioritized_seed_document_urls = [
                *[value for value in prioritized_seed_document_urls if _is_rtf_candidate_url(value)],
                *[value for value in prioritized_seed_document_urls if not _is_rtf_candidate_url(value)],
            ]

        az_prefetched_seed_url_keys: set[str] = set()
        az_failed_seed_retry_urls: List[str] = []
        az_failed_seed_retry_url_keys: set[str] = set()
        if state_code == "AZ" and prioritized_seed_document_urls:
            az_batch_rule_urls = prioritized_seed_document_urls[
                : min(len(prioritized_seed_document_urls), max_fetch, 5)
            ]
            az_batch_remaining_budget_s = min(
                preloop_budget_deadline - time.monotonic(),
                per_state_budget_s - (time.monotonic() - state_start),
            )
            az_batch_timeout_s = _arizona_ranked_fetch_timeout_s(az_batch_remaining_budget_s)
            az_batch_tasks = []
            for rule_url in az_batch_rule_urls:
                lower_rule_url = str(rule_url or "").lower()
                if lower_rule_url.endswith(".pdf") or ".pdf?" in lower_rule_url:
                    az_batch_tasks.append(
                        asyncio.wait_for(
                            _scrape_pdf_candidate_url_with_native_text(rule_url)
                            if _is_arizona_official_pdf_url(rule_url)
                            else _scrape_pdf_candidate_url_with_processor(rule_url),
                            timeout=az_batch_timeout_s,
                        )
                    )
                elif lower_rule_url.endswith(".rtf") or ".rtf?" in lower_rule_url:
                    az_batch_tasks.append(
                        asyncio.wait_for(
                            _scrape_rtf_candidate_url_with_processor(rule_url),
                            timeout=az_batch_timeout_s,
                        )
                    )
                else:
                    az_batch_tasks.append(
                        asyncio.wait_for(
                            live_scraper.scrape(rule_url),
                            timeout=az_batch_timeout_s,
                        )
                    )

            if az_batch_tasks:
                inspected_urls += len(az_batch_rule_urls)
                az_batch_started_at = time.monotonic()
                az_batch_results = await asyncio.gather(*az_batch_tasks, return_exceptions=True)
                for rule_url, az_scraped in zip(az_batch_rule_urls, az_batch_results):
                    az_elapsed_s = max(0.0, time.monotonic() - az_batch_started_at)

                    if isinstance(az_scraped, Exception):
                        _record_az_phase(
                            "seed_batch",
                            url=rule_url,
                            outcome="timeout" if isinstance(az_scraped, asyncio.TimeoutError) else "error",
                            timeout_s=az_batch_timeout_s,
                            elapsed_s=az_elapsed_s,
                            detail=type(az_scraped).__name__,
                        )
                        rule_key = _url_key(rule_url)
                        if _is_pdf_candidate_url(rule_url) and rule_key and rule_key not in az_failed_seed_retry_url_keys:
                            az_failed_seed_retry_url_keys.add(rule_key)
                            az_failed_seed_retry_urls.append(rule_url)
                        continue
                    if az_scraped is None:
                        _record_az_phase(
                            "seed_batch",
                            url=rule_url,
                            outcome="none",
                            timeout_s=az_batch_timeout_s,
                            elapsed_s=az_elapsed_s,
                        )
                        rule_key = _url_key(rule_url)
                        if _is_pdf_candidate_url(rule_url) and rule_key and rule_key not in az_failed_seed_retry_url_keys:
                            az_failed_seed_retry_url_keys.add(rule_key)
                            az_failed_seed_retry_urls.append(rule_url)
                        continue

                    rule_key = _url_key(rule_url)
                    if rule_key:
                        az_prefetched_seed_url_keys.add(rule_key)

                    az_text = str(getattr(az_scraped, "text", "") or "").strip()
                    az_title = str(getattr(az_scraped, "title", "") or "").strip()
                    az_provenance = getattr(az_scraped, "extraction_provenance", None) or {}
                    az_method_value = None
                    if isinstance(az_provenance, dict):
                        az_method_value = az_provenance.get("method")
                    if az_method_value is None:
                        az_method_value = getattr(az_scraped, "method_used", None)
                    accepted_seed = await _append_document_if_rule(
                        rule_url,
                        az_title,
                        az_text,
                        az_method_value,
                        source_phase="seed_batch",
                    )
                    _record_az_phase(
                        "seed_batch",
                        url=rule_url,
                        outcome="success" if accepted_seed else "none",
                        timeout_s=az_batch_timeout_s,
                        elapsed_s=az_elapsed_s,
                    )
                    if len(statutes) >= max_fetch:
                        break

        prioritized_utah_seed_rule_urls: List[str] = []
        if state_code == "UT" and utah_api_rule_urls:
            seen_utah_rule_keys: set[str] = set()
            for rule_url in utah_api_rule_urls:
                rule_key = _url_key(rule_url)
                if not rule_key or rule_key in seen_utah_rule_keys:
                    continue
                if not _url_allowed_for_state(rule_url, allowed_hosts):
                    continue
                seen_utah_rule_keys.add(rule_key)
                prioritized_utah_seed_rule_urls.append(rule_url)
                if len(prioritized_utah_seed_rule_urls) >= min(max_fetch, 8):
                    break

        prioritized_california_bootstrap_document_urls: List[str] = []
        if state_code == "CA" and california_bootstrap_document_urls:
            seen_california_document_keys: set[str] = set()
            for rule_url in california_bootstrap_document_urls:
                rule_key = _url_key(rule_url)
                if not rule_key or rule_key in seen_california_document_keys:
                    continue
                if not _url_allowed_for_state(rule_url, allowed_hosts):
                    continue
                seen_california_document_keys.add(rule_key)
                prioritized_california_bootstrap_document_urls.append(rule_url)
                if len(prioritized_california_bootstrap_document_urls) >= min(max_fetch, 8):
                    break

        prioritized_arizona_seed_rule_urls: List[str] = []
        if state_code == "AZ" and arizona_bootstrap_document_urls:
            seen_arizona_rule_keys: set[str] = set()
            for rule_url in _prioritize_arizona_seed_document_urls(
                arizona_bootstrap_document_urls,
                limit=min(max_fetch * 2, 12),
            ):
                rule_key = _url_key(rule_url)
                if not rule_key or rule_key in seen_arizona_rule_keys:
                    continue
                if not _url_allowed_for_state(rule_url, allowed_hosts):
                    continue
                seen_arizona_rule_keys.add(rule_key)
                prioritized_arizona_seed_rule_urls.append(rule_url)
                if rule_url not in candidate_urls:
                    candidate_urls.append(rule_url)
                seed_expansion_candidates.append((rule_url, _score_candidate_url(rule_url) + 5))
                if len(prioritized_arizona_seed_rule_urls) >= min(max_fetch * 2, 12):
                    break

        prioritized_hawaii_seed_rule_urls: List[str] = []
        if state_code == "HI" and hawaii_bootstrap_document_urls:
            seen_hawaii_rule_keys: set[str] = set()
            for rule_url in hawaii_bootstrap_document_urls:
                rule_key = _url_key(rule_url)
                if not rule_key or rule_key in seen_hawaii_rule_keys:
                    continue
                seen_hawaii_rule_keys.add(rule_key)
                prioritized_hawaii_seed_rule_urls.append(rule_url)
                if rule_url not in candidate_urls:
                    candidate_urls.append(rule_url)
                seed_expansion_candidates.append((rule_url, _score_candidate_url(rule_url) + 5))
                if len(prioritized_hawaii_seed_rule_urls) >= min(max_fetch * 2, 12):
                    break

        prioritized_louisiana_seed_rule_urls: List[str] = []
        if state_code == "LA" and louisiana_bootstrap_document_urls:
            seen_louisiana_rule_keys: set[str] = set()
            for rule_url in louisiana_bootstrap_document_urls:
                rule_key = _url_key(rule_url)
                if not rule_key or rule_key in seen_louisiana_rule_keys:
                    continue
                seen_louisiana_rule_keys.add(rule_key)
                prioritized_louisiana_seed_rule_urls.append(rule_url)
                if rule_url not in candidate_urls:
                    candidate_urls.append(rule_url)
                seed_expansion_candidates.append((rule_url, _score_candidate_url(rule_url) + 5))
                if len(prioritized_louisiana_seed_rule_urls) >= min(max(max_fetch * 2, 8), 16):
                    break

        prioritized_iowa_seed_rule_urls: List[str] = []
        if state_code == "IA" and iowa_bootstrap_document_urls:
            seen_iowa_rule_keys: set[str] = set()
            for rule_url in iowa_bootstrap_document_urls:
                rule_key = _url_key(rule_url)
                if not rule_key or rule_key in seen_iowa_rule_keys:
                    continue
                seen_iowa_rule_keys.add(rule_key)
                prioritized_iowa_seed_rule_urls.append(rule_url)
                if rule_url not in candidate_urls:
                    candidate_urls.append(rule_url)
                seed_expansion_candidates.append((rule_url, _score_candidate_url(rule_url) + 5))
                if len(prioritized_iowa_seed_rule_urls) >= min(max_fetch, 8):
                    break

        prioritized_kansas_seed_rule_urls: List[str] = []
        if state_code == "KS" and kansas_bootstrap_document_urls:
            seen_kansas_rule_keys: set[str] = set()
            for rule_url in kansas_bootstrap_document_urls:
                rule_key = _url_key(rule_url)
                if not rule_key or rule_key in seen_kansas_rule_keys:
                    continue
                if not _url_allowed_for_state(rule_url, allowed_hosts):
                    continue
                seen_kansas_rule_keys.add(rule_key)
                prioritized_kansas_seed_rule_urls.append(rule_url)
                if rule_url not in candidate_urls:
                    candidate_urls.append(rule_url)
                seed_expansion_candidates.append((rule_url, _score_candidate_url(rule_url) + 5))
                if len(prioritized_kansas_seed_rule_urls) >= min(max(max_fetch * 2, 8), 16):
                    break

        prioritized_maryland_seed_rule_urls: List[str] = []
        if state_code == "MD" and maryland_bootstrap_document_urls:
            seen_maryland_rule_keys: set[str] = set()
            for rule_url in maryland_bootstrap_document_urls:
                rule_key = _url_key(rule_url)
                if not rule_key or rule_key in seen_maryland_rule_keys:
                    continue
                if not _url_allowed_for_state(rule_url, allowed_hosts):
                    continue
                seen_maryland_rule_keys.add(rule_key)
                prioritized_maryland_seed_rule_urls.append(rule_url)
                if rule_url not in candidate_urls:
                    candidate_urls.append(rule_url)
                seed_expansion_candidates.append((rule_url, _score_candidate_url(rule_url) + 5))
                if len(prioritized_maryland_seed_rule_urls) >= min(max(max_fetch * 2, 8), 16):
                    break

        official_bootstrap_rule_hit = False

        prioritized_maine_seed_rule_urls: List[str] = []
        if state_code == "ME" and maine_bootstrap_document_urls:
            seen_maine_rule_keys: set[str] = set()
            for rule_url in maine_bootstrap_document_urls:
                rule_key = _url_key(rule_url)
                if not rule_key or rule_key in seen_maine_rule_keys:
                    continue
                if not _url_allowed_for_state(rule_url, allowed_hosts):
                    continue
                seen_maine_rule_keys.add(rule_key)
                prioritized_maine_seed_rule_urls.append(rule_url)
                if rule_url not in candidate_urls:
                    candidate_urls.append(rule_url)
                seed_expansion_candidates.append((rule_url, _score_candidate_url(rule_url) + 5))
                if len(prioritized_maine_seed_rule_urls) >= min(max(max_fetch * 2, 8), 16):
                    break

        for rule_url in prioritized_california_bootstrap_document_urls:
            if len(statutes) >= max_fetch:
                break
            if (time.monotonic() - state_start) >= per_state_budget_s:
                break
            if time.monotonic() >= preloop_budget_deadline:
                break
            inspected_urls += 1
            try:
                california_scraped = await asyncio.wait_for(
                    live_scraper.scrape(rule_url),
                    timeout=25.0,
                )
            except Exception:
                california_scraped = None
            if california_scraped is None:
                continue

            california_text = str(getattr(california_scraped, "text", "") or "").strip()
            california_title = str(getattr(california_scraped, "title", "") or "").strip()
            california_provenance = getattr(california_scraped, "extraction_provenance", None) or {}
            california_method_value = None
            if isinstance(california_provenance, dict):
                california_method_value = california_provenance.get("method")
            if california_method_value is None:
                california_method_value = getattr(california_scraped, "method_used", None)
            await _append_document_if_rule(rule_url, california_title, california_text, california_method_value)

        if state_code == "AZ" and prioritized_arizona_seed_rule_urls:
            arizona_batch_size = max(1, min(effective_fetch_concurrency, max_fetch, 4))
            for batch_start in range(0, len(prioritized_arizona_seed_rule_urls), arizona_batch_size):
                if len(statutes) >= max_fetch:
                    break
                if (time.monotonic() - state_start) >= per_state_budget_s:
                    break

                remaining_slots = max_fetch - len(statutes)
                batch_rule_urls = [
                    rule_url
                    for rule_url in prioritized_arizona_seed_rule_urls[batch_start : batch_start + arizona_batch_size]
                    if _url_key(rule_url) not in direct_doc_urls
                ][:remaining_slots]
                if not batch_rule_urls:
                    continue

                inspected_urls += len(batch_rule_urls)
                batch_timeout_s = max(
                    1.0,
                    min(8.0, preloop_budget_deadline - time.monotonic(), per_state_budget_s - (time.monotonic() - state_start)),
                )
                az_bootstrap_started_at = time.monotonic()
                batch_results = await asyncio.gather(
                    *[
                        asyncio.wait_for(
                            _scrape_rtf_candidate_url_with_processor(rule_url)
                            if _is_rtf_candidate_url(rule_url)
                            else _scrape_pdf_candidate_url_with_processor(rule_url),
                            timeout=batch_timeout_s,
                        )
                        for rule_url in batch_rule_urls
                    ],
                    return_exceptions=True,
                )

                for rule_url, arizona_scraped in zip(batch_rule_urls, batch_results):
                    az_elapsed_s = max(0.0, time.monotonic() - az_bootstrap_started_at)
                    if isinstance(arizona_scraped, Exception):
                        _record_az_phase(
                            "bootstrap_batch",
                            url=rule_url,
                            outcome="timeout" if isinstance(arizona_scraped, asyncio.TimeoutError) else "error",
                            timeout_s=batch_timeout_s,
                            elapsed_s=az_elapsed_s,
                            detail=type(arizona_scraped).__name__,
                        )
                        continue
                    if arizona_scraped is None:
                        _record_az_phase(
                            "bootstrap_batch",
                            url=rule_url,
                            outcome="none",
                            timeout_s=batch_timeout_s,
                            elapsed_s=az_elapsed_s,
                        )
                        continue

                    arizona_text = str(getattr(arizona_scraped, "text", "") or "").strip()
                    arizona_title = str(getattr(arizona_scraped, "title", "") or "").strip()
                    arizona_provenance = getattr(arizona_scraped, "extraction_provenance", None) or {}
                    arizona_method_value = None
                    if isinstance(arizona_provenance, dict):
                        arizona_method_value = arizona_provenance.get("method")
                    if arizona_method_value is None:
                        arizona_method_value = getattr(arizona_scraped, "method_used", None)
                    accepted_bootstrap = await _append_document_if_rule(
                        rule_url,
                        arizona_title,
                        arizona_text,
                        arizona_method_value,
                        source_phase="bootstrap_batch",
                    )
                    _record_az_phase(
                        "bootstrap_batch",
                        url=rule_url,
                        outcome="success" if accepted_bootstrap else "none",
                        timeout_s=batch_timeout_s,
                        elapsed_s=az_elapsed_s,
                    )
                    if len(statutes) >= max_fetch:
                        break

        if state_code == "HI" and prioritized_hawaii_seed_rule_urls:
            hawaii_batch_size = max(1, min(effective_fetch_concurrency, max_fetch, 4))
            for batch_start in range(0, len(prioritized_hawaii_seed_rule_urls), hawaii_batch_size):
                if len(statutes) >= max_fetch:
                    break
                if (time.monotonic() - state_start) >= per_state_budget_s:
                    break

                remaining_slots = max_fetch - len(statutes)
                batch_rule_urls = prioritized_hawaii_seed_rule_urls[
                    batch_start : batch_start + min(hawaii_batch_size, remaining_slots)
                ]
                if not batch_rule_urls:
                    continue

                inspected_urls += len(batch_rule_urls)
                hawaii_timeout_s = max(
                    1.0,
                    min(20.0, preloop_budget_deadline - time.monotonic(), per_state_budget_s - (time.monotonic() - state_start)),
                )
                hawaii_results = await asyncio.gather(
                    *[
                        asyncio.wait_for(
                            _scrape_pdf_candidate_url_with_processor(rule_url)
                            if _is_pdf_candidate_url(rule_url)
                            else (
                                _scrape_rtf_candidate_url_with_processor(rule_url)
                                if _is_rtf_candidate_url(rule_url)
                                else live_scraper.scrape(rule_url)
                            ),
                            timeout=hawaii_timeout_s,
                        )
                        for rule_url in batch_rule_urls
                    ],
                    return_exceptions=True,
                )

                for rule_url, hawaii_scraped in zip(batch_rule_urls, hawaii_results):
                    if isinstance(hawaii_scraped, Exception) or hawaii_scraped is None:
                        continue

                    hawaii_text = str(getattr(hawaii_scraped, "text", "") or "").strip()
                    hawaii_title = str(getattr(hawaii_scraped, "title", "") or "").strip()
                    hawaii_provenance = getattr(hawaii_scraped, "extraction_provenance", None) or {}
                    hawaii_method_value = None
                    if isinstance(hawaii_provenance, dict):
                        hawaii_method_value = hawaii_provenance.get("method")
                    if hawaii_method_value is None:
                        hawaii_method_value = getattr(hawaii_scraped, "method_used", None)
                    await _append_document_if_rule(rule_url, hawaii_title, hawaii_text, hawaii_method_value)
                    if len(statutes) >= max_fetch:
                        break

        if state_code == "MD" and prioritized_maryland_seed_rule_urls:
            maryland_batch_size = max(1, min(effective_fetch_concurrency, max_fetch, 4))
            for batch_start in range(0, len(prioritized_maryland_seed_rule_urls), maryland_batch_size):
                if len(statutes) >= max_fetch:
                    break
                if (time.monotonic() - state_start) >= per_state_budget_s:
                    break
                if time.monotonic() >= preloop_budget_deadline:
                    break

                remaining_slots = max_fetch - len(statutes)
                batch_rule_urls = prioritized_maryland_seed_rule_urls[
                    batch_start : batch_start + min(maryland_batch_size, remaining_slots)
                ]
                if not batch_rule_urls:
                    continue

                inspected_urls += len(batch_rule_urls)
                maryland_timeout_s = max(
                    1.0,
                    min(15.0, preloop_budget_deadline - time.monotonic(), per_state_budget_s - (time.monotonic() - state_start)),
                )
                maryland_results = await asyncio.gather(
                    *[
                        asyncio.wait_for(
                            _scrape_maryland_comar_detail_url(rule_url) or live_scraper.scrape(rule_url),
                            timeout=maryland_timeout_s,
                        )
                        for rule_url in batch_rule_urls
                    ],
                    return_exceptions=True,
                )

                for rule_url, maryland_scraped in zip(batch_rule_urls, maryland_results):
                    if isinstance(maryland_scraped, Exception) or maryland_scraped is None:
                        continue

                    maryland_text = str(getattr(maryland_scraped, "text", "") or "").strip()
                    maryland_title = str(getattr(maryland_scraped, "title", "") or "").strip()
                    maryland_provenance = getattr(maryland_scraped, "extraction_provenance", None) or {}
                    maryland_method_value = None
                    if isinstance(maryland_provenance, dict):
                        maryland_method_value = maryland_provenance.get("method")
                    if maryland_method_value is None:
                        maryland_method_value = getattr(maryland_scraped, "method_used", None)
                    accepted_maryland_bootstrap = await _append_document_if_rule(
                        rule_url,
                        maryland_title,
                        maryland_text,
                        maryland_method_value,
                        source_phase="bootstrap_batch",
                    )
                    official_bootstrap_rule_hit = official_bootstrap_rule_hit or bool(accepted_maryland_bootstrap)
                    if len(statutes) >= max_fetch:
                        break

        if state_code == "ME" and prioritized_maine_seed_rule_urls:
            maine_batch_size = max(1, min(effective_fetch_concurrency, max_fetch, 4))
            for batch_start in range(0, len(prioritized_maine_seed_rule_urls), maine_batch_size):
                if len(statutes) >= max_fetch:
                    break
                if (time.monotonic() - state_start) >= per_state_budget_s:
                    break
                if time.monotonic() >= preloop_budget_deadline:
                    break

                remaining_slots = max_fetch - len(statutes)
                batch_rule_urls = prioritized_maine_seed_rule_urls[
                    batch_start : batch_start + min(maine_batch_size, remaining_slots)
                ]
                if not batch_rule_urls:
                    continue

                inspected_urls += len(batch_rule_urls)
                maine_timeout_s = max(
                    1.0,
                    min(15.0, preloop_budget_deadline - time.monotonic(), per_state_budget_s - (time.monotonic() - state_start)),
                )
                maine_tasks = []
                for rule_url in batch_rule_urls:
                    if _is_docx_candidate_url(rule_url):
                        maine_tasks.append(asyncio.wait_for(_scrape_docx_candidate_url_with_processor(rule_url), timeout=maine_timeout_s))
                    elif _is_pdf_candidate_url(rule_url):
                        maine_tasks.append(asyncio.wait_for(_scrape_pdf_candidate_url_with_processor(rule_url), timeout=maine_timeout_s))
                    else:
                        maine_tasks.append(asyncio.wait_for(live_scraper.scrape(rule_url), timeout=maine_timeout_s))

                maine_results = await asyncio.gather(*maine_tasks, return_exceptions=True)
                for rule_url, maine_scraped in zip(batch_rule_urls, maine_results):
                    if isinstance(maine_scraped, Exception) or maine_scraped is None:
                        continue

                    maine_text = str(getattr(maine_scraped, "text", "") or "").strip()
                    maine_title = str(getattr(maine_scraped, "title", "") or "").strip()
                    maine_provenance = getattr(maine_scraped, "extraction_provenance", None) or {}
                    maine_method_value = None
                    if isinstance(maine_provenance, dict):
                        maine_method_value = maine_provenance.get("method")
                    if maine_method_value is None:
                        maine_method_value = getattr(maine_scraped, "method_used", None)
                    accepted_maine_bootstrap = await _append_document_if_rule(
                        rule_url,
                        maine_title,
                        maine_text,
                        maine_method_value,
                        source_phase="bootstrap_batch",
                    )
                    official_bootstrap_rule_hit = official_bootstrap_rule_hit or bool(accepted_maine_bootstrap)
                    if len(statutes) >= max_fetch:
                        break

        if state_code in {"MD", "ME"} and official_bootstrap_rule_hit and statutes:
            max_fetch = len(statutes)

        if state_code == "LA" and prioritized_louisiana_seed_rule_urls:
            louisiana_batch_size = max(1, min(effective_fetch_concurrency, max_fetch, 4))
            for batch_start in range(0, len(prioritized_louisiana_seed_rule_urls), louisiana_batch_size):
                if len(statutes) >= max_fetch:
                    break
                if (time.monotonic() - state_start) >= per_state_budget_s:
                    break

                remaining_slots = max_fetch - len(statutes)
                batch_rule_urls = prioritized_louisiana_seed_rule_urls[
                    batch_start : batch_start + min(louisiana_batch_size, remaining_slots)
                ]
                if not batch_rule_urls:
                    continue

                inspected_urls += len(batch_rule_urls)
                louisiana_timeout_s = max(
                    1.0,
                    min(6.0, preloop_budget_deadline - time.monotonic(), per_state_budget_s - (time.monotonic() - state_start)),
                )
                louisiana_results = await asyncio.gather(
                    *[
                        asyncio.wait_for(
                            _scrape_pdf_candidate_url_with_native_text(rule_url)
                            if _is_pdf_candidate_url(rule_url)
                            else live_scraper.scrape(rule_url),
                            timeout=louisiana_timeout_s,
                        )
                        for rule_url in batch_rule_urls
                    ],
                    return_exceptions=True,
                )

                for rule_url, louisiana_scraped in zip(batch_rule_urls, louisiana_results):
                    if isinstance(louisiana_scraped, Exception) or louisiana_scraped is None:
                        continue

                    louisiana_text = str(getattr(louisiana_scraped, "text", "") or "").strip()
                    louisiana_title = str(getattr(louisiana_scraped, "title", "") or "").strip()
                    louisiana_provenance = getattr(louisiana_scraped, "extraction_provenance", None) or {}
                    louisiana_method_value = None
                    if isinstance(louisiana_provenance, dict):
                        louisiana_method_value = louisiana_provenance.get("method")
                    if louisiana_method_value is None:
                        louisiana_method_value = getattr(louisiana_scraped, "method_used", None)
                    await _append_document_if_rule(rule_url, louisiana_title, louisiana_text, louisiana_method_value)
                    if len(statutes) >= max_fetch:
                        break

        if state_code == "IA" and prioritized_iowa_seed_rule_urls:
            iowa_batch_size = max(1, min(effective_fetch_concurrency, max_fetch, 4))
            for batch_start in range(0, len(prioritized_iowa_seed_rule_urls), iowa_batch_size):
                if len(statutes) >= max_fetch:
                    break
                if (time.monotonic() - state_start) >= per_state_budget_s:
                    break

                remaining_slots = max_fetch - len(statutes)
                batch_rule_urls = prioritized_iowa_seed_rule_urls[
                    batch_start : batch_start + min(iowa_batch_size, remaining_slots)
                ]
                if not batch_rule_urls:
                    continue

                inspected_urls += len(batch_rule_urls)
                iowa_timeout_s = max(
                    1.0,
                    min(6.0, preloop_budget_deadline - time.monotonic(), per_state_budget_s - (time.monotonic() - state_start)),
                )
                iowa_results = await asyncio.gather(
                    *[
                        asyncio.wait_for(
                            _scrape_pdf_candidate_url_with_native_text(rule_url)
                            if _is_pdf_candidate_url(rule_url)
                            else live_scraper.scrape(rule_url),
                            timeout=iowa_timeout_s,
                        )
                        for rule_url in batch_rule_urls
                    ],
                    return_exceptions=True,
                )

                for rule_url, iowa_scraped in zip(batch_rule_urls, iowa_results):
                    if isinstance(iowa_scraped, Exception) or iowa_scraped is None:
                        continue

                    iowa_text = str(getattr(iowa_scraped, "text", "") or "").strip()
                    iowa_title = str(getattr(iowa_scraped, "title", "") or "").strip()
                    iowa_provenance = getattr(iowa_scraped, "extraction_provenance", None) or {}
                    iowa_method_value = None
                    if isinstance(iowa_provenance, dict):
                        iowa_method_value = iowa_provenance.get("method")
                    if iowa_method_value is None:
                        iowa_method_value = getattr(iowa_scraped, "method_used", None)
                    await _append_document_if_rule(rule_url, iowa_title, iowa_text, iowa_method_value)
                    if len(statutes) >= max_fetch:
                        break

        if state_code == "KS" and prioritized_kansas_seed_rule_urls:
            kansas_batch_size = max(1, min(effective_fetch_concurrency, max_fetch, 4))
            for batch_start in range(0, len(prioritized_kansas_seed_rule_urls), kansas_batch_size):
                if len(statutes) >= max_fetch:
                    break
                if (time.monotonic() - state_start) >= per_state_budget_s:
                    break

                remaining_slots = max_fetch - len(statutes)
                batch_rule_urls = prioritized_kansas_seed_rule_urls[
                    batch_start : batch_start + min(kansas_batch_size, remaining_slots)
                ]
                if not batch_rule_urls:
                    continue

                inspected_urls += len(batch_rule_urls)
                kansas_timeout_s = max(
                    1.0,
                    min(12.0, preloop_budget_deadline - time.monotonic(), per_state_budget_s - (time.monotonic() - state_start)),
                )
                kansas_results = await asyncio.gather(
                    *[
                        asyncio.wait_for(
                            live_scraper.scrape(rule_url),
                            timeout=kansas_timeout_s,
                        )
                        for rule_url in batch_rule_urls
                    ],
                    return_exceptions=True,
                )

                for rule_url, kansas_scraped in zip(batch_rule_urls, kansas_results):
                    if isinstance(kansas_scraped, Exception) or kansas_scraped is None:
                        continue

                    kansas_text = str(getattr(kansas_scraped, "text", "") or "").strip()
                    kansas_title = str(getattr(kansas_scraped, "title", "") or "").strip()
                    kansas_provenance = getattr(kansas_scraped, "extraction_provenance", None) or {}
                    kansas_method_value = None
                    if isinstance(kansas_provenance, dict):
                        kansas_method_value = kansas_provenance.get("method")
                    if kansas_method_value is None:
                        kansas_method_value = getattr(kansas_scraped, "method_used", None)
                    await _append_document_if_rule(
                        rule_url,
                        kansas_title,
                        kansas_text,
                        kansas_method_value,
                        source_phase="kansas_bootstrap_batch",
                    )
                    if len(statutes) >= max_fetch:
                        break

        utah_batch_size = max(1, min(effective_fetch_concurrency, max_fetch, 4))
        for batch_start in range(0, len(prioritized_utah_seed_rule_urls), utah_batch_size):
            if len(statutes) >= max_fetch:
                break
            if (time.monotonic() - state_start) >= per_state_budget_s:
                break

            remaining_slots = max_fetch - len(statutes)
            batch_rule_urls = prioritized_utah_seed_rule_urls[batch_start : batch_start + min(utah_batch_size, remaining_slots)]
            if not batch_rule_urls:
                continue

            inspected_urls += len(batch_rule_urls)
            batch_timeout_s = max(1.0, min(40.0, per_state_budget_s - (time.monotonic() - state_start)))
            batch_results = await asyncio.gather(
                *[
                    asyncio.wait_for(
                        _scrape_utah_rule_detail_via_public_download(rule_url),
                        timeout=batch_timeout_s,
                    )
                    for rule_url in batch_rule_urls
                ],
                return_exceptions=True,
            )

            for rule_url, utah_scraped in zip(batch_rule_urls, batch_results):
                if isinstance(utah_scraped, Exception) or utah_scraped is None:
                    continue

                utah_text = str(getattr(utah_scraped, "text", "") or "").strip()
                utah_title = str(getattr(utah_scraped, "title", "") or "").strip()
                utah_provenance = getattr(utah_scraped, "extraction_provenance", None) or {}
                utah_method_value = None
                if isinstance(utah_provenance, dict):
                    utah_method_value = utah_provenance.get("method")
                if utah_method_value is None:
                    utah_method_value = getattr(utah_scraped, "method_used", None)
                await _append_document_if_rule(rule_url, utah_title, utah_text, utah_method_value)
                if len(statutes) >= max_fetch:
                    break

        utah_official_bootstrap_recovered_rules = (
            state_code == "UT"
            and bool(prioritized_utah_seed_rule_urls)
            and len(statutes) > 0
        )

        louisiana_official_bootstrap_recovered_rules = (
            state_code == "LA"
            and bool(prioritized_louisiana_seed_rule_urls)
            and len(statutes) >= min(max_fetch, max(1, len(prioritized_louisiana_seed_rule_urls)))
            and any(_url_key(rule_url) in direct_doc_urls for rule_url in prioritized_louisiana_seed_rule_urls)
        )

        iowa_official_bootstrap_recovered_rules = (
            state_code == "IA"
            and bool(prioritized_iowa_seed_rule_urls)
            and len(statutes) > 0
            and any(_url_key(rule_url) in direct_doc_urls for rule_url in prioritized_iowa_seed_rule_urls)
        )

        kansas_official_bootstrap_recovered_rules = (
            state_code == "KS"
            and bool(prioritized_kansas_seed_rule_urls)
            and len(statutes) > 0
            and any(_url_key(rule_url) in direct_doc_urls for rule_url in prioritized_kansas_seed_rule_urls)
        )
        maryland_official_bootstrap_recovered_rules = (
            state_code == "MD"
            and bool(prioritized_maryland_seed_rule_urls)
            and len(statutes) > 0
            and any(_url_key(rule_url) in direct_doc_urls for rule_url in prioritized_maryland_seed_rule_urls)
        )
        maine_official_bootstrap_recovered_rules = (
            state_code == "ME"
            and bool(prioritized_maine_seed_rule_urls)
            and len(statutes) > 0
            and any(_url_key(rule_url) in direct_doc_urls for rule_url in prioritized_maine_seed_rule_urls)
        )
        ranked_direct_exclude_urls = direct_doc_urls | preseed_substantive_url_keys
        if direct_detail_ready and len(prioritized_seed_document_urls) > 1:
            ranked_direct_exclude_urls = ranked_direct_exclude_urls | {
                url for url in prioritized_seed_document_urls if _url_key(url)
            }
            if state_code == "AK" and alaska_bootstrap_document_urls:
                ranked_direct_exclude_urls = ranked_direct_exclude_urls | {
                    url for url in alaska_bootstrap_document_urls if _url_key(url)
                }
        if state_code == "TN" and tennessee_bootstrap_document_urls:
            ranked_direct_exclude_urls = ranked_direct_exclude_urls | {
                url for url in prioritized_seed_document_urls if _url_key(url)
            }
        if state_code == "IA" and prioritized_iowa_seed_rule_urls:
            ranked_direct_exclude_urls = ranked_direct_exclude_urls | {
                url for url in prioritized_iowa_seed_rule_urls if _url_key(url)
            }
        if state_code == "KS" and prioritized_kansas_seed_rule_urls:
            ranked_direct_exclude_urls = ranked_direct_exclude_urls | {
                url for url in prioritized_kansas_seed_rule_urls if _url_key(url)
            }
        if state_code == "MD" and prioritized_maryland_seed_rule_urls:
            ranked_direct_exclude_urls = ranked_direct_exclude_urls | {
                url for url in prioritized_maryland_seed_rule_urls if _url_key(url)
            }
        if state_code == "ME" and prioritized_maine_seed_rule_urls:
            ranked_direct_exclude_urls = ranked_direct_exclude_urls | {
                url for url in prioritized_maine_seed_rule_urls if _url_key(url)
            }

        prioritized_ranked_document_urls = _prioritized_direct_detail_urls_from_candidates(
            ranked_urls,
            limit=(
                min(max_fetch * 5, 24)
                if state_code == "AZ"
                else min(max_fetch * 4, 24)
                if state_code == "AR"
                else min(max_fetch * 3, 12)
            ),
            exclude_urls=ranked_direct_exclude_urls,
        )
        _record_co_progress(
            "direct_detail_queue_ready",
            ranked=len(ranked_urls),
            queued=len(prioritized_ranked_document_urls),
            seed_docs=len(prioritized_seed_document_urls),
            direct_ready=int(bool(direct_detail_ready)),
        )

        if state_code == "AZ" and prioritized_ranked_document_urls:
            az_late_retry_urls = _prioritized_arizona_late_retry_urls(
                prioritized_ranked_document_urls,
                limit=min(max_fetch, 5),
                extra_preferred_urls=az_failed_seed_retry_urls,
                exclude_urls=ranked_direct_exclude_urls,
            )
            az_late_retry_url_keys = {
                key for key in (_url_key(url) for url in az_late_retry_urls) if key
            }
            if az_late_retry_url_keys:
                prioritized_ranked_document_urls = az_late_retry_urls + [
                    url
                    for url in prioritized_ranked_document_urls
                    if _url_key(url) not in az_late_retry_url_keys
                ]
            az_code_page_url = next(
                (
                    url
                    for url in prioritized_ranked_document_urls
                    if _url_key(url) == _url_key("https://azsos.gov/rules/arizona-administrative-code")
                ),
                None,
            )
            if az_code_page_url:
                prioritized_ranked_document_urls = [az_code_page_url] + [
                    url
                    for url in prioritized_ranked_document_urls
                    if _url_key(url) != _url_key(az_code_page_url)
                ]

        az_prefetched_ranked_url_keys: set[str] = set()
        if state_code == "AZ" and prioritized_ranked_document_urls:
            az_ranked_rule_urls = prioritized_ranked_document_urls[: min(len(prioritized_ranked_document_urls), max_fetch * 4, 20)]
            az_ranked_batch_size = 1
            for batch_start in range(0, len(az_ranked_rule_urls), az_ranked_batch_size):
                if len(statutes) >= max_fetch:
                    break
                if (time.monotonic() - state_start) >= per_state_budget_s:
                    break
                if time.monotonic() >= preloop_budget_deadline:
                    break
                remaining_slots = max_fetch - len(statutes)
                batch_rule_urls = [
                    rule_url
                    for rule_url in az_ranked_rule_urls[batch_start : batch_start + az_ranked_batch_size]
                    if _url_key(rule_url) not in direct_doc_urls
                ][:remaining_slots]
                if not batch_rule_urls:
                    continue

                inspected_urls += len(batch_rule_urls)
                az_ranked_remaining_budget_s = min(
                    preloop_budget_deadline - time.monotonic(),
                    per_state_budget_s - (time.monotonic() - state_start),
                )
                az_ranked_timeout_s = _arizona_ranked_fetch_timeout_s(az_ranked_remaining_budget_s)
                if az_ranked_timeout_s <= 0.0:
                    break
                az_ranked_tasks = []
                for rule_url in batch_rule_urls:
                    lower_rule_url = str(rule_url or "").lower()
                    if lower_rule_url.endswith(".pdf") or ".pdf?" in lower_rule_url:
                        az_ranked_tasks.append(
                            asyncio.wait_for(
                                _scrape_pdf_candidate_url_with_native_text(rule_url)
                                if _is_arizona_official_pdf_url(rule_url)
                                else _scrape_pdf_candidate_url_with_processor(rule_url),
                                timeout=az_ranked_timeout_s,
                            )
                        )
                    elif lower_rule_url.endswith(".rtf") or ".rtf?" in lower_rule_url:
                        az_ranked_tasks.append(
                            asyncio.wait_for(
                                _scrape_rtf_candidate_url_with_processor(rule_url),
                                timeout=az_ranked_timeout_s,
                            )
                        )
                    else:
                        az_ranked_tasks.append(
                            asyncio.wait_for(
                                live_scraper.scrape(rule_url),
                                timeout=az_ranked_timeout_s,
                            )
                        )

                az_ranked_started_at = time.monotonic()
                az_ranked_results = await asyncio.gather(*az_ranked_tasks, return_exceptions=True)
                for rule_url, az_scraped in zip(batch_rule_urls, az_ranked_results):
                    az_elapsed_s = max(0.0, time.monotonic() - az_ranked_started_at)
                    if isinstance(az_scraped, Exception):
                        _record_az_phase(
                            "ranked_batch",
                            url=rule_url,
                            outcome="timeout" if isinstance(az_scraped, asyncio.TimeoutError) else "error",
                            timeout_s=az_ranked_timeout_s,
                            elapsed_s=az_elapsed_s,
                            detail=type(az_scraped).__name__,
                        )
                        continue
                    if az_scraped is None:
                        _record_az_phase(
                            "ranked_batch",
                            url=rule_url,
                            outcome="none",
                            timeout_s=az_ranked_timeout_s,
                            elapsed_s=az_elapsed_s,
                        )
                        continue

                    rule_key = _url_key(rule_url)
                    if rule_key:
                        az_prefetched_ranked_url_keys.add(rule_key)

                    az_text = str(getattr(az_scraped, "text", "") or "").strip()
                    az_title = str(getattr(az_scraped, "title", "") or "").strip()
                    az_provenance = getattr(az_scraped, "extraction_provenance", None) or {}
                    az_method_value = None
                    if isinstance(az_provenance, dict):
                        az_method_value = az_provenance.get("method")
                    if az_method_value is None:
                        az_method_value = getattr(az_scraped, "method_used", None)
                    accepted_ranked = await _append_document_if_rule(
                        rule_url,
                        az_title,
                        az_text,
                        az_method_value,
                        source_phase="ranked_batch",
                    )
                    _record_az_phase(
                        "ranked_batch",
                        url=rule_url,
                        outcome="success" if accepted_ranked else "none",
                        timeout_s=az_ranked_timeout_s,
                        elapsed_s=az_elapsed_s,
                    )
                    if len(statutes) >= max_fetch:
                        break

        for document_url in prioritized_ranked_document_urls:
            if len(statutes) >= max_fetch:
                break
            if (time.monotonic() - state_start) >= per_state_budget_s:
                break
            if state_code == "AZ" and _url_key(document_url) in az_prefetched_ranked_url_keys:
                _record_az_phase("direct_detail", url=document_url, outcome="skipped")
                continue
            remaining_prefetch_budget_s = preloop_budget_deadline - time.monotonic()
            if remaining_prefetch_budget_s <= 1.0:
                break
            direct_scraped = None
            fetch_document_url = str(document_url or "").strip()
            lower_document_url = fetch_document_url.lower()
            direct_timeout_s = max(1.0, min(25.0, remaining_prefetch_budget_s))
            az_direct_started_at = time.monotonic()
            az_direct_used_fallback = False
            inspected_urls += 1
            try:
                if lower_document_url.endswith(".pdf") or ".pdf?" in lower_document_url:
                    direct_scraped = await asyncio.wait_for(
                        _scrape_pdf_candidate_url_with_processor(fetch_document_url),
                        timeout=direct_timeout_s,
                    )
                elif lower_document_url.endswith(".rtf") or ".rtf?" in lower_document_url:
                    direct_scraped = await asyncio.wait_for(
                        _scrape_rtf_candidate_url_with_processor(fetch_document_url),
                        timeout=direct_timeout_s,
                    )
                elif _is_docx_candidate_url(fetch_document_url):
                    direct_scraped = await asyncio.wait_for(
                        _scrape_docx_candidate_url_with_processor(fetch_document_url),
                        timeout=direct_timeout_s,
                    )
                elif state_code == "AL":
                    direct_scraped = await asyncio.wait_for(
                        _scrape_alabama_rule_detail_via_api(fetch_document_url),
                        timeout=direct_timeout_s,
                    )
                elif state_code == "IN":
                    direct_scraped = await asyncio.wait_for(
                        _scrape_indiana_rule_detail_via_api(fetch_document_url),
                        timeout=direct_timeout_s,
                    )
                elif state_code == "NH":
                    direct_scraped = await asyncio.wait_for(
                        _scrape_new_hampshire_archived_rule_detail(document_url),
                        timeout=direct_timeout_s,
                    )
                elif state_code == "GA":
                    direct_scraped = await asyncio.wait_for(
                        _scrape_georgia_rule_detail_via_ajax(fetch_document_url),
                        timeout=direct_timeout_s,
                    )
                elif state_code == "MT":
                    direct_scraped = await asyncio.wait_for(
                        _scrape_montana_rule_detail_via_api(fetch_document_url),
                        timeout=direct_timeout_s,
                    )
                elif state_code == "SD":
                    direct_scraped = await asyncio.wait_for(
                        _scrape_south_dakota_rule_detail_via_api(fetch_document_url),
                        timeout=direct_timeout_s,
                    )
                elif state_code == "OK":
                    direct_scraped = await asyncio.wait_for(
                        _scrape_oklahoma_rule_detail_via_api(fetch_document_url),
                        timeout=direct_timeout_s,
                    )
                else:
                    direct_scraped = await asyncio.wait_for(
                        live_scraper.scrape(fetch_document_url),
                        timeout=direct_timeout_s,
                    )
            except Exception as exc:
                if state_code == "AZ":
                    _record_az_phase(
                        "direct_detail",
                        url=fetch_document_url,
                        outcome="timeout" if isinstance(exc, asyncio.TimeoutError) else "error",
                        timeout_s=direct_timeout_s,
                        elapsed_s=max(0.0, time.monotonic() - az_direct_started_at),
                        detail=type(exc).__name__,
                    )
                direct_scraped = None
            if direct_scraped is None:
                remaining_prefetch_budget_s = preloop_budget_deadline - time.monotonic()
                if remaining_prefetch_budget_s <= 1.0:
                    break
                document_host = urlparse(fetch_document_url).netloc
                fetch_api = live_fetch_api if _prefers_live_fetch(fetch_document_url) else direct_fetch_api
                try:
                    fetched = await asyncio.wait_for(
                        _run_blocking_fetch(
                            fetch_api.fetch,
                            UnifiedFetchRequest(
                                url=fetch_document_url,
                                timeout_seconds=35,
                                mode=OperationMode.BALANCED,
                                domain=".gov" if document_host.endswith(".gov") else "legal",
                            ),
                        ),
                        timeout=max(1.0, min(18.0, remaining_prefetch_budget_s)),
                    )
                    _record_rate_limit_metadata(fetched)
                    fetched_doc = getattr(fetched, "document", None)
                    if fetched_doc is not None:
                        az_direct_used_fallback = True
                        direct_scraped = SimpleNamespace(
                            text=str(getattr(fetched_doc, "text", "") or "").strip(),
                            title=str(getattr(fetched_doc, "title", "") or "").strip(),
                            html=str(getattr(fetched_doc, "html", "") or ""),
                            extraction_provenance=getattr(fetched_doc, "extraction_provenance", None),
                            method_used=getattr(fetched_doc, "method_used", None),
                        )
                except Exception as exc:
                    if state_code == "AZ":
                        _record_az_phase(
                            "direct_detail",
                            url=fetch_document_url,
                            outcome="timeout" if isinstance(exc, asyncio.TimeoutError) else "error",
                            timeout_s=max(1.0, min(18.0, remaining_prefetch_budget_s)),
                            elapsed_s=max(0.0, time.monotonic() - az_direct_started_at),
                            detail=f"fallback:{type(exc).__name__}",
                        )
                    direct_scraped = None
            if direct_scraped is None:
                _record_az_phase(
                    "direct_detail",
                    url=fetch_document_url,
                    outcome="none",
                    timeout_s=direct_timeout_s,
                    elapsed_s=max(0.0, time.monotonic() - az_direct_started_at),
                )
                continue

            direct_text = str(getattr(direct_scraped, "text", "") or "").strip()
            direct_title = str(getattr(direct_scraped, "title", "") or "").strip()
            direct_provenance = getattr(direct_scraped, "extraction_provenance", None) or {}
            direct_method_value = None
            if isinstance(direct_provenance, dict):
                direct_method_value = direct_provenance.get("method")
            if direct_method_value is None:
                direct_method_value = getattr(direct_scraped, "method_used", None)
            direct_method_value = getattr(direct_method_value, "value", direct_method_value)
            accepted_direct = await _append_document_if_rule(
                document_url,
                direct_title,
                direct_text,
                direct_method_value,
                source_phase="direct_detail",
            )
            _record_az_phase(
                "direct_detail",
                url=document_url,
                outcome="fallback_success" if accepted_direct and az_direct_used_fallback else ("success" if accepted_direct else "none"),
                timeout_s=direct_timeout_s,
                elapsed_s=max(0.0, time.monotonic() - az_direct_started_at),
            )
            direct_html = str(getattr(direct_scraped, "html", "") or "")
            if not accepted_direct and _looks_like_rule_inventory_page(text=direct_text, title=direct_title, url=document_url):
                document_host = urlparse(document_url).netloc
                for link_url in _candidate_links_from_html(
                    direct_html,
                    base_host=document_host,
                    page_url=document_url,
                    limit=24,
                    allowed_hosts=allowed_hosts,
                ):
                    link_score = _score_candidate_url(link_url)
                    if link_score <= 0:
                        continue
                    seed_expansion_candidates.append((link_url, link_score + 3))

        _record_co_progress(
            "direct_detail_complete",
            accepted=len(statutes),
            inspected=inspected_urls,
            seed_expansions=len(seed_expansion_candidates),
        )

        if state_code == "AZ" and len(statutes) < max_fetch:
            az_late_retry_urls = _prioritized_arizona_late_retry_urls(
                prioritized_ranked_document_urls,
                limit=min(max_fetch - len(statutes), 5),
                extra_preferred_urls=az_failed_seed_retry_urls,
                exclude_urls={url for url in direct_doc_urls if url},
            )
            for document_url in az_late_retry_urls:
                if len(statutes) >= max_fetch:
                    break
                if _url_key(document_url) in direct_doc_urls:
                    continue
                remaining_state_budget_s = per_state_budget_s - (time.monotonic() - state_start)
                az_late_timeout_s = _arizona_late_retry_timeout_s(remaining_state_budget_s)
                if az_late_timeout_s <= 0.0:
                    break

                late_scraped = None
                fetch_document_url = str(document_url or "").strip()
                lower_document_url = fetch_document_url.lower()
                inspected_urls += 1
                az_late_started_at = time.monotonic()
                try:
                    if lower_document_url.endswith(".pdf") or ".pdf?" in lower_document_url:
                        late_scraped = await asyncio.wait_for(
                            _scrape_pdf_candidate_url_with_processor(fetch_document_url),
                            timeout=az_late_timeout_s,
                        )
                    elif lower_document_url.endswith(".rtf") or ".rtf?" in lower_document_url:
                        late_scraped = await asyncio.wait_for(
                            _scrape_rtf_candidate_url_with_processor(fetch_document_url),
                            timeout=az_late_timeout_s,
                        )
                    else:
                        late_scraped = await asyncio.wait_for(
                            live_scraper.scrape(fetch_document_url),
                            timeout=az_late_timeout_s,
                        )
                except Exception as exc:
                    _record_az_phase(
                        "late_retry",
                        url=fetch_document_url,
                        outcome="timeout" if isinstance(exc, asyncio.TimeoutError) else "error",
                        timeout_s=az_late_timeout_s,
                        elapsed_s=max(0.0, time.monotonic() - az_late_started_at),
                        detail=type(exc).__name__,
                    )
                    late_scraped = None
                if late_scraped is None:
                    _record_az_phase(
                        "late_retry",
                        url=fetch_document_url,
                        outcome="none",
                        timeout_s=az_late_timeout_s,
                        elapsed_s=max(0.0, time.monotonic() - az_late_started_at),
                    )
                    continue

                late_text = str(getattr(late_scraped, "text", "") or "").strip()
                late_title = str(getattr(late_scraped, "title", "") or "").strip()
                late_provenance = getattr(late_scraped, "extraction_provenance", None) or {}
                late_method_value = None
                if isinstance(late_provenance, dict):
                    late_method_value = late_provenance.get("method")
                if late_method_value is None:
                    late_method_value = getattr(late_scraped, "method_used", None)
                late_method_value = getattr(late_method_value, "value", late_method_value)
                accepted_late = await _append_document_if_rule(
                    document_url,
                    late_title,
                    late_text,
                    late_method_value,
                    source_phase="late_retry",
                )
                _record_az_phase(
                    "late_retry",
                    url=document_url,
                    outcome="success" if accepted_late else "none",
                    timeout_s=az_late_timeout_s,
                    elapsed_s=max(0.0, time.monotonic() - az_late_started_at),
                )

            az_last_chance_retry_urls = _prioritized_arizona_late_retry_urls(
                [],
                limit=1,
                extra_preferred_urls=[
                    "https://apps.azsos.gov/public_services/Title_15/15-03.rtf",
                    "https://apps.azsos.gov/public_services/Title_07/7-02.rtf",
                    "https://apps.azsos.gov/public_services/Title_18/18-01.rtf",
                ],
                exclude_urls={url for url in direct_doc_urls if url},
            )
            for document_url in az_last_chance_retry_urls:
                if len(statutes) >= max_fetch:
                    break
                remaining_state_budget_s = per_state_budget_s - (time.monotonic() - state_start)
                az_late_timeout_s = min(12.0, _arizona_late_retry_timeout_s(remaining_state_budget_s))
                if az_late_timeout_s <= 0.0:
                    break

                late_scraped = None
                inspected_urls += 1
                az_last_chance_started_at = time.monotonic()
                try:
                    late_scraped = await asyncio.wait_for(
                        _scrape_rtf_candidate_url_with_processor(document_url),
                        timeout=az_late_timeout_s,
                    )
                except Exception as exc:
                    _record_az_phase(
                        "last_chance",
                        url=document_url,
                        outcome="timeout" if isinstance(exc, asyncio.TimeoutError) else "error",
                        timeout_s=az_late_timeout_s,
                        elapsed_s=max(0.0, time.monotonic() - az_last_chance_started_at),
                        detail=type(exc).__name__,
                    )
                    late_scraped = None
                if late_scraped is None:
                    _record_az_phase(
                        "last_chance",
                        url=document_url,
                        outcome="none",
                        timeout_s=az_late_timeout_s,
                        elapsed_s=max(0.0, time.monotonic() - az_last_chance_started_at),
                    )
                    continue

                late_text = str(getattr(late_scraped, "text", "") or "").strip()
                late_title = str(getattr(late_scraped, "title", "") or "").strip()
                late_provenance = getattr(late_scraped, "extraction_provenance", None) or {}
                late_method_value = None
                if isinstance(late_provenance, dict):
                    late_method_value = late_provenance.get("method")
                if late_method_value is None:
                    late_method_value = getattr(late_scraped, "method_used", None)
                late_method_value = getattr(late_method_value, "value", late_method_value)
                accepted_last_chance = await _append_document_if_rule(
                    document_url,
                    late_title,
                    late_text,
                    late_method_value,
                    source_phase="last_chance",
                )
                _record_az_phase(
                    "last_chance",
                    url=document_url,
                    outcome="success" if accepted_last_chance else "none",
                    timeout_s=az_late_timeout_s,
                    elapsed_s=max(0.0, time.monotonic() - az_last_chance_started_at),
                )

        prioritized_alabama_seed_rule_urls: List[str] = []
        prioritized_south_dakota_seed_rule_urls: List[str] = []
        prioritized_indiana_seed_rule_urls: List[str] = []
        if state_code == "IN":
            try:
                indiana_api_rule_urls = await asyncio.wait_for(
                    _discover_indiana_rule_document_urls(limit=min(max_fetch * 3, 12)),
                    timeout=25.0,
                )
            except Exception:
                indiana_api_rule_urls = []
            seen_indiana_rule_keys: set[str] = set()
            for rule_url in indiana_api_rule_urls:
                rule_key = _url_key(rule_url)
                if not rule_key or rule_key in seen_indiana_rule_keys:
                    continue
                if not _url_allowed_for_state(rule_url, allowed_hosts):
                    continue
                seen_indiana_rule_keys.add(rule_key)
                prioritized_indiana_seed_rule_urls.append(rule_url)
                if rule_url not in candidate_urls:
                    candidate_urls.append(rule_url)
                seed_expansion_candidates.append((rule_url, _score_candidate_url(rule_url) + 4))
                if len(prioritized_indiana_seed_rule_urls) >= min(max_fetch, 8):
                    break
            if prioritized_indiana_seed_rule_urls:
                source_breakdown["indiana_api_bootstrap"] = len(prioritized_indiana_seed_rule_urls)

        if state_code == "SD":
            seen_south_dakota_rule_keys: set[str] = set()
            for rule_url in south_dakota_bootstrap_document_urls:
                rule_key = _url_key(rule_url)
                if not rule_key or rule_key in seen_south_dakota_rule_keys:
                    continue
                if not _url_allowed_for_state(rule_url, allowed_hosts):
                    continue
                seen_south_dakota_rule_keys.add(rule_key)
                prioritized_south_dakota_seed_rule_urls.append(rule_url)
                if rule_url not in candidate_urls:
                    candidate_urls.append(rule_url)
                seed_expansion_candidates.append((rule_url, _score_candidate_url(rule_url) + 5))
                if len(prioritized_south_dakota_seed_rule_urls) >= min(max_fetch * 2, 12):
                    break

        prioritized_alabama_seed_rule_urls: List[str] = []
        if state_code == "AL":
            seen_alabama_rule_keys: set[str] = set()
            for rule_url in alabama_bootstrap_document_urls:
                rule_key = _url_key(rule_url)
                if not rule_key or rule_key in seen_alabama_rule_keys:
                    continue
                if not _url_allowed_for_state(rule_url, allowed_hosts):
                    continue
                seen_alabama_rule_keys.add(rule_key)
                prioritized_alabama_seed_rule_urls.append(rule_url)
                if rule_url not in candidate_urls:
                    candidate_urls.append(rule_url)
                seed_expansion_candidates.append((rule_url, _score_candidate_url(rule_url) + 4))
                if len(prioritized_alabama_seed_rule_urls) >= min(max_fetch, 24):
                    break

        for rule_url in prioritized_south_dakota_seed_rule_urls:
            if len(statutes) >= max_fetch:
                break
            if (time.monotonic() - state_start) >= per_state_budget_s:
                break
            inspected_urls += 1
            try:
                south_dakota_scraped = await asyncio.wait_for(
                    _scrape_south_dakota_rule_detail_via_api(rule_url),
                    timeout=15.0,
                )
            except Exception:
                south_dakota_scraped = None
            if south_dakota_scraped is None:
                continue

            south_dakota_text = str(getattr(south_dakota_scraped, "text", "") or "").strip()
            south_dakota_title = str(getattr(south_dakota_scraped, "title", "") or "").strip()
            south_dakota_provenance = getattr(south_dakota_scraped, "extraction_provenance", None) or {}
            south_dakota_method_value = None
            if isinstance(south_dakota_provenance, dict):
                south_dakota_method_value = south_dakota_provenance.get("method")
            if south_dakota_method_value is None:
                south_dakota_method_value = getattr(south_dakota_scraped, "method_used", None)
            await _append_document_if_rule(rule_url, south_dakota_title, south_dakota_text, south_dakota_method_value)

        prioritized_michigan_seed_rule_urls: List[str] = []
        if state_code == "MI":
            seen_michigan_rule_keys: set[str] = set()
            for rule_url in michigan_bootstrap_document_urls:
                rule_key = _url_key(rule_url)
                if not rule_key or rule_key in seen_michigan_rule_keys:
                    continue
                if not _url_allowed_for_state(rule_url, allowed_hosts):
                    continue
                seen_michigan_rule_keys.add(rule_key)
                prioritized_michigan_seed_rule_urls.append(rule_url)
                if rule_url not in candidate_urls:
                    candidate_urls.append(rule_url)
                seed_expansion_candidates.append((rule_url, _score_candidate_url(rule_url) + 5))
                if len(prioritized_michigan_seed_rule_urls) >= min(max_fetch * 2, 12):
                    break

        prioritized_alaska_seed_rule_urls: List[str] = []
        if state_code == "AK":
            seen_alaska_rule_keys: set[str] = set()
            for rule_url in alaska_bootstrap_document_urls:
                rule_key = _url_key(rule_url)
                if not rule_key or rule_key in seen_alaska_rule_keys:
                    continue
                if not _url_allowed_for_state(rule_url, allowed_hosts):
                    continue
                seen_alaska_rule_keys.add(rule_key)
                prioritized_alaska_seed_rule_urls.append(rule_url)
                if rule_url not in candidate_urls:
                    candidate_urls.append(rule_url)
                seed_expansion_candidates.append((rule_url, _score_candidate_url(rule_url) + 5))
                if len(prioritized_alaska_seed_rule_urls) >= min(max_fetch * 3, 20):
                    break

        prioritized_texas_seed_rule_urls: List[str] = []
        if state_code == "TX" and texas_bootstrap_document_urls:
            seen_texas_rule_keys: set[str] = set()
            for rule_url in texas_bootstrap_document_urls:
                rule_key = _url_key(rule_url)
                if not rule_key or rule_key in seen_texas_rule_keys:
                    continue
                if not _url_allowed_for_state(rule_url, allowed_hosts):
                    continue
                seen_texas_rule_keys.add(rule_key)
                prioritized_texas_seed_rule_urls.append(rule_url)
                if rule_url not in candidate_urls:
                    candidate_urls.append(rule_url)
                seed_expansion_candidates.append((rule_url, _score_candidate_url(rule_url) + 5))
                if len(prioritized_texas_seed_rule_urls) >= min(max_fetch * 2, 12):
                    break

        prioritized_oklahoma_seed_rule_urls: List[str] = []
        if state_code == "OK" and oklahoma_bootstrap_document_urls:
            seen_oklahoma_rule_keys: set[str] = set()
            for rule_url in oklahoma_bootstrap_document_urls:
                rule_key = _url_key(rule_url)
                if not rule_key or rule_key in seen_oklahoma_rule_keys:
                    continue
                if not _url_allowed_for_state(rule_url, allowed_hosts):
                    continue
                seen_oklahoma_rule_keys.add(rule_key)
                prioritized_oklahoma_seed_rule_urls.append(rule_url)
                if rule_url not in candidate_urls:
                    candidate_urls.append(rule_url)
                seed_expansion_candidates.append((rule_url, _score_candidate_url(rule_url) + 5))
                if len(prioritized_oklahoma_seed_rule_urls) >= min(max_fetch * 2, 12):
                    break

        prioritized_tennessee_seed_rule_urls: List[str] = []
        if state_code == "TN" and tennessee_bootstrap_document_urls:
            seen_tennessee_rule_keys: set[str] = set()
            for rule_url in tennessee_bootstrap_document_urls:
                rule_key = _url_key(rule_url)
                if not rule_key or rule_key in seen_tennessee_rule_keys:
                    continue
                if not _url_allowed_for_state(rule_url, allowed_hosts):
                    continue
                seen_tennessee_rule_keys.add(rule_key)
                prioritized_tennessee_seed_rule_urls.append(rule_url)
                if rule_url not in candidate_urls:
                    candidate_urls.append(rule_url)
                seed_expansion_candidates.append((rule_url, _score_candidate_url(rule_url) + 5))
                if len(prioritized_tennessee_seed_rule_urls) >= min(max_fetch * 2, 12):
                    break

        for rule_url in prioritized_alabama_seed_rule_urls:
            if len(statutes) >= max_fetch:
                break
            if (time.monotonic() - state_start) >= per_state_budget_s:
                break
            if time.monotonic() >= preloop_budget_deadline:
                break
            inspected_urls += 1
            try:
                alabama_scraped = await asyncio.wait_for(
                    _scrape_alabama_rule_detail_via_api(rule_url),
                    timeout=20.0,
                )
            except Exception:
                alabama_scraped = None
            if alabama_scraped is None:
                continue

            alabama_text = str(getattr(alabama_scraped, "text", "") or "").strip()
            alabama_title = str(getattr(alabama_scraped, "title", "") or "").strip()
            alabama_provenance = getattr(alabama_scraped, "extraction_provenance", None) or {}
            alabama_method_value = None
            if isinstance(alabama_provenance, dict):
                alabama_method_value = alabama_provenance.get("method")
            if alabama_method_value is None:
                alabama_method_value = getattr(alabama_scraped, "method_used", None)
            await _append_document_if_rule(rule_url, alabama_title, alabama_text, alabama_method_value)

        for rule_url in prioritized_michigan_seed_rule_urls:
            if len(statutes) >= max_fetch:
                break
            if (time.monotonic() - state_start) >= per_state_budget_s:
                break
            if time.monotonic() >= preloop_budget_deadline:
                break
            inspected_urls += 1
            try:
                michigan_scraped = await asyncio.wait_for(
                    live_scraper.scrape(rule_url),
                    timeout=25.0,
                )
            except Exception:
                michigan_scraped = None
            if michigan_scraped is None:
                continue

            michigan_text = str(getattr(michigan_scraped, "text", "") or "").strip()
            michigan_title = str(getattr(michigan_scraped, "title", "") or "").strip()
            michigan_provenance = getattr(michigan_scraped, "extraction_provenance", None) or {}
            michigan_method_value = None
            if isinstance(michigan_provenance, dict):
                michigan_method_value = michigan_provenance.get("method")
            if michigan_method_value is None:
                michigan_method_value = getattr(michigan_scraped, "method_used", None)
            await _append_document_if_rule(rule_url, michigan_title, michigan_text, michigan_method_value)

        for rule_url in prioritized_alaska_seed_rule_urls:
            if len(statutes) >= max_fetch:
                break
            if (time.monotonic() - state_start) >= per_state_budget_s:
                break
            if time.monotonic() >= preloop_budget_deadline:
                break
            inspected_urls += 1
            try:
                alaska_scraped = await asyncio.wait_for(
                    _scrape_alaska_rule_detail_via_print_view(rule_url),
                    timeout=20.0,
                )
            except Exception:
                alaska_scraped = None
            if alaska_scraped is None:
                continue

            alaska_text = str(getattr(alaska_scraped, "text", "") or "").strip()
            alaska_title = str(getattr(alaska_scraped, "title", "") or "").strip()
            alaska_provenance = getattr(alaska_scraped, "extraction_provenance", None) or {}
            alaska_method_value = None
            if isinstance(alaska_provenance, dict):
                alaska_method_value = alaska_provenance.get("method")
            if alaska_method_value is None:
                alaska_method_value = getattr(alaska_scraped, "method_used", None)
            await _append_document_if_rule(rule_url, alaska_title, alaska_text, alaska_method_value)

        for rule_url in prioritized_texas_seed_rule_urls:
            if len(statutes) >= max_fetch:
                break
            if (time.monotonic() - state_start) >= per_state_budget_s:
                break
            inspected_urls += 1
            try:
                texas_scraped = await asyncio.wait_for(
                    _scrape_texas_tac_rule_detail_via_playwright(rule_url),
                    timeout=30.0,
                )
            except Exception:
                texas_scraped = None
            if texas_scraped is None:
                continue

            texas_text = str(getattr(texas_scraped, "text", "") or "").strip()
            texas_title = str(getattr(texas_scraped, "title", "") or "").strip()
            texas_provenance = getattr(texas_scraped, "extraction_provenance", None) or {}
            texas_method_value = None
            if isinstance(texas_provenance, dict):
                texas_method_value = texas_provenance.get("method")
            if texas_method_value is None:
                texas_method_value = getattr(texas_scraped, "method_used", None)
            await _append_document_if_rule(rule_url, texas_title, texas_text, texas_method_value)

        for rule_url in prioritized_oklahoma_seed_rule_urls:
            if len(statutes) >= max_fetch:
                break
            if (time.monotonic() - state_start) >= per_state_budget_s:
                break
            if time.monotonic() >= preloop_budget_deadline:
                break
            inspected_urls += 1
            try:
                oklahoma_scraped = await asyncio.wait_for(
                    _scrape_oklahoma_rule_detail_via_api(rule_url),
                    timeout=20.0,
                )
            except Exception:
                oklahoma_scraped = None
            if oklahoma_scraped is None:
                continue

            oklahoma_text = str(getattr(oklahoma_scraped, "text", "") or "").strip()
            oklahoma_title = str(getattr(oklahoma_scraped, "title", "") or "").strip()
            oklahoma_provenance = getattr(oklahoma_scraped, "extraction_provenance", None) or {}
            oklahoma_method_value = None
            if isinstance(oklahoma_provenance, dict):
                oklahoma_method_value = oklahoma_provenance.get("method")
            if oklahoma_method_value is None:
                oklahoma_method_value = getattr(oklahoma_scraped, "method_used", None)
            await _append_document_if_rule(rule_url, oklahoma_title, oklahoma_text, oklahoma_method_value)

        tennessee_batch_size = max(1, min(effective_fetch_concurrency, max_fetch, 4))
        for batch_start in range(0, len(prioritized_tennessee_seed_rule_urls), tennessee_batch_size):
            if len(statutes) >= max_fetch:
                break
            if (time.monotonic() - state_start) >= per_state_budget_s:
                break
            if time.monotonic() >= preloop_budget_deadline:
                break

            remaining_slots = max_fetch - len(statutes)
            batch_rule_urls = [
                rule_url
                for rule_url in prioritized_tennessee_seed_rule_urls[batch_start : batch_start + tennessee_batch_size]
                if _url_key(rule_url) not in direct_doc_urls
            ][:remaining_slots]
            if not batch_rule_urls:
                continue

            inspected_urls += len(batch_rule_urls)
            batch_timeout_s = max(
                1.0,
                min(12.0, preloop_budget_deadline - time.monotonic(), per_state_budget_s - (time.monotonic() - state_start)),
            )
            batch_results = await asyncio.gather(
                *[
                    asyncio.wait_for(
                        _scrape_pdf_candidate_url_with_processor(rule_url),
                        timeout=batch_timeout_s,
                    )
                    for rule_url in batch_rule_urls
                ],
                return_exceptions=True,
            )

            for rule_url, tennessee_scraped in zip(batch_rule_urls, batch_results):
                if isinstance(tennessee_scraped, Exception) or tennessee_scraped is None:
                    continue

                tennessee_text = str(getattr(tennessee_scraped, "text", "") or "").strip()
                tennessee_title = str(getattr(tennessee_scraped, "title", "") or "").strip()
                tennessee_provenance = getattr(tennessee_scraped, "extraction_provenance", None) or {}
                tennessee_method_value = None
                if isinstance(tennessee_provenance, dict):
                    tennessee_method_value = tennessee_provenance.get("method")
                if tennessee_method_value is None:
                    tennessee_method_value = getattr(tennessee_scraped, "method_used", None)
                await _append_document_if_rule(rule_url, tennessee_title, tennessee_text, tennessee_method_value)
                if len(statutes) >= max_fetch:
                    break

        for document_url in prioritized_seed_document_urls:
            if len(statutes) >= max_fetch:
                break
            if (time.monotonic() - state_start) >= per_state_budget_s:
                break
            if state_code == "AZ" and _url_key(document_url) in az_prefetched_seed_url_keys:
                continue
            if _url_key(document_url) in direct_doc_urls:
                continue
            if time.monotonic() >= preloop_budget_deadline:
                break
            remaining_prefetch_budget_s = preloop_budget_deadline - time.monotonic()
            if remaining_prefetch_budget_s <= 1.0:
                break
            direct_scraped = None
            lower_document_url = str(document_url or "").lower()
            # Official direct-detail pages can require a slower hydrated browser pass
            # than generic seed pages; give them more of the preloop budget before
            # falling back to the fetch API, which may return no document at all.
            direct_timeout_s = max(1.0, min(25.0, remaining_prefetch_budget_s))
            inspected_urls += 1
            try:
                if lower_document_url.endswith(".pdf") or ".pdf?" in lower_document_url:
                    direct_scraped = await asyncio.wait_for(
                        _scrape_pdf_candidate_url_with_processor(document_url),
                        timeout=direct_timeout_s,
                    )
                elif lower_document_url.endswith(".rtf") or ".rtf?" in lower_document_url:
                    direct_scraped = await asyncio.wait_for(
                        _scrape_rtf_candidate_url_with_processor(document_url),
                        timeout=direct_timeout_s,
                    )
                elif _is_docx_candidate_url(document_url):
                    direct_scraped = await asyncio.wait_for(
                        _scrape_docx_candidate_url_with_processor(document_url),
                        timeout=direct_timeout_s,
                    )
                elif state_code == "AL":
                    direct_scraped = await asyncio.wait_for(
                        _scrape_alabama_rule_detail_via_api(document_url),
                        timeout=direct_timeout_s,
                    )
                elif state_code == "IN":
                    direct_scraped = await asyncio.wait_for(
                        _scrape_indiana_rule_detail_via_api(document_url),
                        timeout=direct_timeout_s,
                    )
                elif state_code == "MT":
                    direct_scraped = await asyncio.wait_for(
                        _scrape_montana_rule_detail_via_api(document_url),
                        timeout=direct_timeout_s,
                    )
                elif state_code == "SD":
                    direct_scraped = await asyncio.wait_for(
                        _scrape_south_dakota_rule_detail_via_api(document_url),
                        timeout=direct_timeout_s,
                    )
                else:
                    direct_scraped = await asyncio.wait_for(
                        live_scraper.scrape(document_url),
                        timeout=direct_timeout_s,
                    )
            except Exception:
                direct_scraped = None
            if direct_scraped is None:
                remaining_prefetch_budget_s = preloop_budget_deadline - time.monotonic()
                if remaining_prefetch_budget_s <= 1.0:
                    break
                document_host = urlparse(document_url).netloc
                fetch_api = live_fetch_api if _prefers_live_fetch(document_url) else direct_fetch_api
                try:
                    fetched = await asyncio.wait_for(
                        _run_blocking_fetch(
                            fetch_api.fetch,
                            UnifiedFetchRequest(
                                url=document_url,
                                timeout_seconds=35,
                                mode=OperationMode.BALANCED,
                                domain=".gov" if document_host.endswith(".gov") else "legal",
                            ),
                        ),
                        timeout=max(1.0, min(18.0, remaining_prefetch_budget_s)),
                    )
                    _record_rate_limit_metadata(fetched)
                    fetched_doc = getattr(fetched, "document", None)
                    if fetched_doc is not None:
                        direct_scraped = SimpleNamespace(
                            text=str(getattr(fetched_doc, "text", "") or "").strip(),
                            title=str(getattr(fetched_doc, "title", "") or "").strip(),
                            html=str(getattr(fetched_doc, "html", "") or ""),
                            extraction_provenance=getattr(fetched_doc, "extraction_provenance", None),
                            method_used=getattr(fetched_doc, "method_used", None),
                        )
                except Exception:
                    direct_scraped = None
            if direct_scraped is None:
                continue

            direct_text = str(getattr(direct_scraped, "text", "") or "").strip()
            direct_title = str(getattr(direct_scraped, "title", "") or "").strip()
            direct_provenance = getattr(direct_scraped, "extraction_provenance", None) or {}
            direct_method_value = None
            if isinstance(direct_provenance, dict):
                direct_method_value = direct_provenance.get("method")
            if direct_method_value is None:
                direct_method_value = getattr(direct_scraped, "method_used", None)
            direct_method_value = getattr(direct_method_value, "value", direct_method_value)
            await _append_document_if_rule(document_url, direct_title, direct_text, direct_method_value, source_phase="preseed_direct_detail")
            direct_html = str(getattr(direct_scraped, "html", "") or "")
            if _looks_like_rule_inventory_page(text=direct_text, title=direct_title, url=document_url):
                document_host = urlparse(document_url).netloc
                for link_url in _candidate_links_from_html(
                    direct_html,
                    base_host=document_host,
                    page_url=document_url,
                    limit=24,
                    allowed_hosts=allowed_hosts,
                ):
                    link_score = _score_candidate_url(link_url)
                    if link_score <= 0:
                        continue
                    seed_expansion_candidates.append((link_url, link_score + 3))

        # Give curated/official entrypoints one deterministic direct fetch pass.
        for seed_url in ordered_seed_urls[:6]:
            if len(statutes) >= max(1, int(max_fetch_per_state)):
                break
            if time.monotonic() >= preloop_budget_deadline:
                break
            if _state_seed_expansion_backlog_is_ready(
                state_code=state_code,
                seed_expansion_candidates=seed_expansion_candidates,
                max_fetch=max_fetch,
            ):
                break
            seed_key = _url_key(seed_url)
            if seed_key and seed_key in preseed_substantive_url_keys:
                continue
            host = urlparse(seed_url).netloc
            fetch_api = live_fetch_api if _prefers_live_fetch(seed_url) else direct_fetch_api
            try:
                fetched = await asyncio.wait_for(
                    _run_blocking_fetch(
                        fetch_api.fetch,
                        UnifiedFetchRequest(
                            url=seed_url,
                            timeout_seconds=35,
                            mode=OperationMode.BALANCED,
                            domain=".gov" if host.endswith(".gov") else "legal",
                        ),
                    ),
                    timeout=40.0,
                )
                _record_rate_limit_metadata(fetched)
                fetched_doc = getattr(fetched, "document", None)
                fetched_text = str(getattr(fetched_doc, "text", "") or "").strip()
                fetched_title = str(getattr(fetched_doc, "title", "") or "").strip()
                fetched_html = str(getattr(fetched_doc, "html", "") or "")
                method_value = None
                if fetched_doc is not None:
                    method_value = (getattr(fetched_doc, "extraction_provenance", {}) or {}).get("method")
                accepted_seed = await _append_document_if_rule(seed_url, fetched_title, fetched_text, method_value, source_phase="seed_fetch")
                inventory_seed = _looks_like_rule_inventory_page(text=fetched_text, title=fetched_title, url=seed_url)
                if inventory_seed:
                    for rule_url in _candidate_montana_rule_urls_from_text(
                        text=fetched_html or fetched_text,
                        url=seed_url,
                        limit=24,
                    ):
                        seed_expansion_candidates.append((rule_url, _score_candidate_url(rule_url) + 4))
                    for link_url in _candidate_links_from_html(
                        fetched_html,
                        base_host=host,
                        page_url=seed_url,
                        limit=24,
                    ):
                        link_score = _score_candidate_url(link_url)
                        if link_score <= 0:
                            continue
                        seed_expansion_candidates.append((link_url, link_score + 2))
                    for rule_url in _candidate_utah_rule_urls_from_public_api(
                        url=seed_url,
                        limit=24,
                    ):
                        seed_expansion_candidates.append((rule_url, _score_candidate_url(rule_url) + 4))

                # Official seed entrypoints still need a hydrated browser pass so SPA-backed
                # indexes can expose child chapter/article links even when the initial fetch
                # only returned placeholder text.
                if accepted_seed or inventory_seed or _prefers_live_fetch(seed_url) or bool(_OFFICIAL_RULE_INDEX_URL_RE.search(seed_url)):
                    try:
                        seed_scrape = await asyncio.wait_for(live_scraper.scrape(seed_url), timeout=25.0)
                        _record_rate_limit_metadata(seed_scrape)
                        seed_scrape_text = str(getattr(seed_scrape, "text", "") or "").strip()
                        seed_scrape_title = str(getattr(seed_scrape, "title", "") or "").strip()
                        seed_scrape_html = str(getattr(seed_scrape, "html", "") or "")
                        live_method_value = None
                        seed_scrape_provenance = getattr(seed_scrape, "extraction_provenance", None) or {}
                        if isinstance(seed_scrape_provenance, dict):
                            live_method_value = seed_scrape_provenance.get("method")
                        await _append_document_if_rule(seed_url, seed_scrape_title, seed_scrape_text, live_method_value, source_phase="seed_live_scrape")
                        for rule_url in _candidate_montana_rule_urls_from_text(
                            text=seed_scrape_html or seed_scrape_text,
                            url=seed_url,
                            limit=24,
                        ):
                            seed_expansion_candidates.append((rule_url, _score_candidate_url(rule_url) + 4))
                        for link_url in _candidate_links_from_scrape(
                            seed_scrape,
                            base_host=host,
                            page_url=seed_url,
                            limit=24,
                            allowed_hosts=allowed_hosts,
                        ):
                            link_score = _score_candidate_url(link_url)
                            if link_score <= 0:
                                continue
                            seed_expansion_candidates.append((link_url, link_score + 3))
                        for link_url in _candidate_links_from_html(
                            seed_scrape_html,
                            base_host=host,
                            page_url=seed_url,
                            limit=24,
                            allowed_hosts=allowed_hosts,
                        ):
                            link_score = _score_candidate_url(link_url)
                            if link_score <= 0:
                                continue
                            seed_expansion_candidates.append((link_url, link_score + 2))
                        for rule_url in _candidate_utah_rule_urls_from_public_api(
                            url=seed_url,
                            limit=24,
                        ):
                            seed_expansion_candidates.append((rule_url, _score_candidate_url(rule_url) + 5))
                    except Exception:
                        pass
                if _state_seed_expansion_backlog_is_ready(
                    state_code=state_code,
                    seed_expansion_candidates=seed_expansion_candidates,
                    max_fetch=max_fetch,
                ):
                    break
            except Exception:
                pass

        prioritized_seed_expansion_document_urls = _prioritized_direct_detail_urls_from_candidates(
            seed_expansion_candidates,
            limit=min(max_fetch * 3, 12),
            exclude_urls=direct_doc_urls,
        )

        for document_url in prioritized_seed_expansion_document_urls:
            if len(statutes) >= max_fetch:
                break
            if (time.monotonic() - state_start) >= per_state_budget_s:
                break
            remaining_prefetch_budget_s = preloop_budget_deadline - time.monotonic()
            if remaining_prefetch_budget_s <= 1.0:
                break
            expanded_scraped = None
            fetch_document_url = str(document_url or "").strip()
            lower_document_url = fetch_document_url.lower()
            direct_timeout_s = max(1.0, min(12.0, remaining_prefetch_budget_s))
            inspected_urls += 1
            try:
                if lower_document_url.endswith(".pdf") or ".pdf?" in lower_document_url:
                    expanded_scraped = await asyncio.wait_for(
                        _scrape_pdf_candidate_url_with_processor(fetch_document_url),
                        timeout=direct_timeout_s,
                    )
                elif lower_document_url.endswith(".rtf") or ".rtf?" in lower_document_url:
                    expanded_scraped = await asyncio.wait_for(
                        _scrape_rtf_candidate_url_with_processor(fetch_document_url),
                        timeout=direct_timeout_s,
                    )
                elif _is_docx_candidate_url(fetch_document_url):
                    expanded_scraped = await asyncio.wait_for(
                        _scrape_docx_candidate_url_with_processor(fetch_document_url),
                        timeout=direct_timeout_s,
                    )
                elif state_code == "AL":
                    expanded_scraped = await asyncio.wait_for(
                        _scrape_alabama_rule_detail_via_api(fetch_document_url),
                        timeout=direct_timeout_s,
                    )
                elif state_code == "IN":
                    expanded_scraped = await asyncio.wait_for(
                        _scrape_indiana_rule_detail_via_api(fetch_document_url),
                        timeout=direct_timeout_s,
                    )
                elif state_code == "NH":
                    expanded_scraped = await asyncio.wait_for(
                        _scrape_new_hampshire_archived_rule_detail(document_url),
                        timeout=direct_timeout_s,
                    )
                else:
                    expanded_scraped = await asyncio.wait_for(
                        live_scraper.scrape(fetch_document_url),
                        timeout=direct_timeout_s,
                    )
            except Exception:
                expanded_scraped = None
            if expanded_scraped is None:
                continue

            expanded_text = str(getattr(expanded_scraped, "text", "") or "").strip()
            expanded_title = str(getattr(expanded_scraped, "title", "") or "").strip()
            expanded_provenance = getattr(expanded_scraped, "extraction_provenance", None) or {}
            expanded_method_value = None
            if isinstance(expanded_provenance, dict):
                expanded_method_value = expanded_provenance.get("method")
            if expanded_method_value is None:
                expanded_method_value = getattr(expanded_scraped, "method_used", None)
            expanded_method_value = getattr(expanded_method_value, "value", expanded_method_value)
            await _append_document_if_rule(document_url, expanded_title, expanded_text, expanded_method_value, source_phase="seed_expansion")

        try:
            if "discovered" in locals() and isinstance(discovered, dict):
                for fetch_row in discovered.get("results", []) or []:
                    if not isinstance(fetch_row, dict):
                        continue
                    document = fetch_row.get("document") or {}
                    if not isinstance(document, dict):
                        continue
                    doc_url = str(document.get("url") or fetch_row.get("url") or "").strip()
                    if not doc_url.startswith(("http://", "https://")):
                        continue
                    doc_text = str(document.get("text") or "").strip()
                    doc_title = str(document.get("title") or "").strip()
                    method_used = document.get("method_used")
                    method_value = getattr(method_used, "value", method_used)
                    if not await _append_document_if_rule(doc_url, doc_title, doc_text, method_value, source_phase="discovered_result"):
                        continue
                    if len(statutes) >= max(1, int(max_fetch_per_state)):
                        break
        except Exception:
            pass

        # Montana's `rules.mt.gov` host is often easier to traverse from Common Crawl
        # than from repeated origin fetches. Supplement the candidate pool with an
        # archive-first domain scrape before the bounded live crawl loop runs.
        if (
            state_code == "MT"
            and not montana_bootstrap_document_urls
            and len(statutes) < min(max(1, int(max_fetch_per_state)), 12)
        ):
            try:
                cc_domain_results = await asyncio.wait_for(
                    scraper.scrape_domain(
                        "https://rules.mt.gov/",
                        max_pages=min(max(24, max_candidates_per_state), 48),
                    ),
                    timeout=80.0,
                )
                for scraped in cc_domain_results or []:
                    if not getattr(scraped, "success", False):
                        continue
                    cc_url = str(getattr(scraped, "url", "") or "").strip()
                    if not cc_url.startswith(("http://", "https://")):
                        continue
                    cc_text = str(getattr(scraped, "text", "") or "").strip()
                    cc_title = str(getattr(scraped, "title", "") or "").strip()
                    cc_html = str(getattr(scraped, "html", "") or "")
                    cc_host = urlparse(cc_url).netloc
                    method_used = getattr(scraped, "method_used", None)
                    method_value = getattr(method_used, "value", method_used) if method_used else None

                    candidate_urls.append(cc_url)
                    source_breakdown["common_crawl_domain"] = int(source_breakdown.get("common_crawl_domain", 0)) + 1

                    await _append_document_if_rule(cc_url, cc_title, cc_text, method_value)

                    if not _looks_like_rule_inventory_page(text=cc_text, title=cc_title, url=cc_url):
                        continue

                    for rule_url in _candidate_montana_rule_urls_from_text(
                        text=cc_html or cc_text,
                        url=cc_url,
                        limit=32,
                    ):
                        seed_expansion_candidates.append((rule_url, _score_candidate_url(rule_url) + 5))
                    for link_url in _candidate_links_from_scrape(
                        scraped,
                        base_host=cc_host,
                        page_url=cc_url,
                        limit=32,
                        allowed_hosts=allowed_hosts,
                    ):
                        link_score = _score_candidate_url(link_url)
                        if link_score <= 0:
                            continue
                        seed_expansion_candidates.append((link_url, link_score + 3))
                    for link_url in _candidate_links_from_html(
                        cc_html,
                        base_host=cc_host,
                        page_url=cc_url,
                        limit=32,
                        allowed_hosts=allowed_hosts,
                    ):
                        link_score = _score_candidate_url(link_url)
                        if link_score <= 0:
                            continue
                        seed_expansion_candidates.append((link_url, link_score + 3))
                    if len(statutes) >= max(1, int(max_fetch_per_state)):
                        break
            except Exception:
                pass

        vermont_official_seed_recovered_rules = (
            state_code == "VT"
            and len(statutes) > 0
            and any(_url_key(seed_url) in direct_doc_urls for seed_url in prioritized_seed_document_urls)
        )

        max_candidates = max(1, int(max_candidates_per_state))
        pending = [] if (utah_official_bootstrap_recovered_rules or louisiana_official_bootstrap_recovered_rules or iowa_official_bootstrap_recovered_rules or kansas_official_bootstrap_recovered_rules) else _build_initial_pending_candidates(
            ranked_urls=ranked_urls,
            seed_expansion_candidates=seed_expansion_candidates,
            max_candidates=max_candidates,
        )
        if vermont_official_seed_recovered_rules:
            pending = [
                item
                for item in pending
                if urlparse(item[0]).netloc.lower() == "secure.vermont.gov"
                and _is_immediate_direct_detail_candidate_url(item[0])
            ]
        if state_code == "MT" and montana_bootstrap_document_urls:
            pending = [
                item
                for item in pending
                if not _is_montana_inventory_candidate_url(item[0])
            ]
        seen_urls = set(direct_doc_urls)
        pending_candidate_keys: set[str] = {
            _url_key(candidate_url)
            for candidate_url, _ in pending
            if _url_key(candidate_url)
        }
        inspected_url_samples: List[str] = []
        deep_discovery_calls = 0
        vermont_lexis_signin_block_count = 0
        vermont_lexis_access_blocked = False
        base_hosts = {
            urlparse(str(seed).strip()).netloc
            for seed in seed_urls
            if str(seed).strip().startswith(("http://", "https://"))
        }
        prioritized_seed_keys = {_url_key(url) for url in seed_urls}

        def _enqueue_pending_candidate(candidate_url: str, candidate_score: int) -> bool:
            candidate_key = _url_key(candidate_url)
            if not candidate_key or candidate_key in seen_urls or candidate_key in pending_candidate_keys:
                return False
            if _NON_ADMIN_SOURCE_URL_RE.search(candidate_url):
                return False
            if not _url_allowed_for_state(candidate_url, allowed_hosts):
                return False
            normalized_score = int(candidate_score)
            if normalized_score <= 0:
                normalized_score = _score_candidate_url(candidate_url)
            if normalized_score <= 0:
                return False
            if state_code == "MT" and montana_bootstrap_document_urls and _is_montana_inventory_candidate_url(candidate_url):
                return False
            pending.append((candidate_url, int(normalized_score)))
            pending_candidate_keys.add(candidate_key)
            return True

        async def _scrape_candidate_url(url: str):
            alabama_scraped = await _scrape_alabama_rule_detail_via_api(url)
            if alabama_scraped is not None:
                return alabama_scraped
            montana_scraped = await _scrape_montana_rule_detail_via_api(url)
            if montana_scraped is not None:
                return montana_scraped
            maryland_scraped = await _scrape_maryland_comar_detail_url(url)
            if maryland_scraped is not None:
                return maryland_scraped
            vermont_lexis_scraped = await asyncio.to_thread(_scrape_vermont_lexis_document_candidate, url)
            if vermont_lexis_scraped is not None:
                return vermont_lexis_scraped
            south_dakota_scraped = await _scrape_south_dakota_rule_detail_via_api(url)
            if south_dakota_scraped is not None:
                return south_dakota_scraped
            new_hampshire_scraped = await _scrape_new_hampshire_archived_rule_detail(url)
            if new_hampshire_scraped is not None:
                return new_hampshire_scraped
            wyoming_scraped = await _scrape_wyoming_rule_detail_via_ajax(url)
            if wyoming_scraped is not None:
                return wyoming_scraped
            georgia_scraped = await _scrape_georgia_rule_detail_via_ajax(url)
            if georgia_scraped is not None:
                return georgia_scraped
            utah_scraped = await _scrape_utah_rule_detail_via_public_download(url)
            if utah_scraped is not None:
                return utah_scraped
            texas_scraped = await _scrape_texas_tac_rule_detail_via_playwright(url)
            if texas_scraped is not None:
                return texas_scraped
            oklahoma_scraped = await _scrape_oklahoma_rule_detail_via_api(url)
            if oklahoma_scraped is not None:
                return oklahoma_scraped
            pdf_scraped = await _scrape_pdf_candidate_url_with_processor(url)
            if pdf_scraped is not None:
                return pdf_scraped
            rtf_scraped = await _scrape_rtf_candidate_url_with_processor(url)
            if rtf_scraped is not None:
                return rtf_scraped
            docx_scraped = await _scrape_docx_candidate_url_with_processor(url)
            if docx_scraped is not None:
                return docx_scraped
            scrape_url = str(url or "").strip()
            host = urlparse(scrape_url).netloc
            active_scraper = live_scraper if (_url_key(url) in prioritized_seed_keys or host in base_hosts) else scraper
            scraped = await active_scraper.scrape(scrape_url)
            # When the scraper receives a browser challenge page (e.g. Cloudflare), escalate
            # through cloudscraper → cfscrape → Wayback Machine → Common Crawl.
            scraped_text = str(getattr(scraped, "text", "") or "").strip()
            if scraped_text and _looks_like_browser_challenge(
                status_code=int(getattr(scraped, "status_code", 200) or 200),
                content_type="text/html",
                head=scraped_text[:1024],
            ):
                bypass = await _fetch_html_bypassing_challenge(url)
                if bypass is not None:
                    return SimpleNamespace(
                        text=bypass["text"],
                        html=bypass.get("html") or "",
                        title=str(getattr(scraped, "title", "") or ""),
                        links=[],
                        success=True,
                        status_code=200,
                    )
            return scraped

        while pending and len(statutes) < max_fetch and inspected_urls < max(4, max_candidates * 4):
            if (time.monotonic() - state_start) >= per_state_budget_s:
                break
            if _should_abort_vermont_after_lexis_block(
                state_code=state_code,
                vermont_lexis_access_blocked=vermont_lexis_access_blocked,
                statutes_count=len(statutes),
            ):
                break

            batch_candidates: List[tuple[str, int]] = []
            while (
                pending
                and len(batch_candidates) < effective_fetch_concurrency
                and len(statutes) + len(batch_candidates) < max_fetch
                and inspected_urls < max(4, max_candidates * 4)
            ):
                url, score = pending.pop(0)
                key = _url_key(url)
                if not key or key in seen_urls:
                    continue
                seen_urls.add(key)
                inspected_urls += 1
                if url not in inspected_url_samples and len(inspected_url_samples) < 16:
                    inspected_url_samples.append(url)
                batch_candidates.append((url, score))

            if not batch_candidates:
                continue

            scrape_results = await asyncio.gather(
                *[
                    asyncio.wait_for(_scrape_candidate_url(url), timeout=25.0)
                    for url, _ in batch_candidates
                ],
                return_exceptions=True,
            )

            for (url, score), scrape_result in zip(batch_candidates, scrape_results):
                if isinstance(scrape_result, Exception):
                    continue

                try:
                    scraped = scrape_result
                    _record_rate_limit_metadata(scraped)
                    text = str(getattr(scraped, "text", "") or "").strip()
                    title = str(getattr(scraped, "title", "") or "").strip()
                    fetched_html = str(getattr(scraped, "html", "") or "")
                    title, text = await _normalize_candidate_document_content(
                        url=url,
                        title=title,
                        text=text,
                    )
                    current_host = urlparse(url).netloc
                    final_url = str(getattr(scraped, "url", "") or "").strip()
                    final_host = urlparse(final_url).netloc.lower() if final_url else ""
                    official_index_page = _looks_like_official_rule_index_page(text=text, title=title, url=url)
                    inventory_page = _looks_like_rule_inventory_page(text=text, title=title, url=url)

                    if (
                        state_code == "VT"
                        and current_host.lower() == "advance.lexis.com"
                        and _VT_LEXIS_DOC_PATH_RE.fullmatch(urlparse(url).path or "")
                        and (
                            final_host == "signin.lexisnexis.com"
                            or _VT_LEXIS_SHELL_TEXT_RE.search(f"{title}\n{text}")
                        )
                    ):
                        vermont_lexis_signin_block_count += 1
                        if vermont_lexis_signin_block_count >= 3 and not vermont_lexis_access_blocked:
                            vermont_lexis_access_blocked = True
                            pending = [
                                item
                                for item in pending
                                if not (
                                    urlparse(item[0]).netloc.lower() == "advance.lexis.com"
                                    and _VT_LEXIS_DOC_PATH_RE.fullmatch(urlparse(item[0]).path or "")
                                )
                            ]
                        continue

                    if not _is_substantive_rule_text(
                        text=text,
                        title=title,
                        url=url,
                        min_chars=min_text_chars,
                    ):
                        # Dynamic official rule indexes can render as a thin JS shell through
                        # the lightweight scraper even when the fuller fetch path has real text.
                        if (_url_key(url) in prioritized_seed_keys or current_host in base_hosts) and not (official_index_page or inventory_page):
                            fetch_api = live_fetch_api if _prefers_live_fetch(url) else direct_fetch_api
                            try:
                                fetched = await asyncio.wait_for(
                                    _run_blocking_fetch(
                                        fetch_api.fetch,
                                        UnifiedFetchRequest(
                                            url=url,
                                            timeout_seconds=35,
                                            mode=OperationMode.BALANCED,
                                            domain=".gov" if current_host.endswith(".gov") else "legal",
                                        ),
                                    ),
                                    timeout=40.0,
                                )
                                _record_rate_limit_metadata(fetched)
                                fetched_doc = getattr(fetched, "document", None)
                                fetched_text = str(getattr(fetched_doc, "text", "") or "").strip()
                                fetched_title = str(getattr(fetched_doc, "title", "") or "").strip()
                                fetched_html = str(getattr(fetched_doc, "html", "") or "")
                                fetched_title, fetched_text = await _normalize_candidate_document_content(
                                    url=url,
                                    title=fetched_title,
                                    text=fetched_text,
                                )
                                if _is_substantive_rule_text(
                                    text=fetched_text,
                                    title=fetched_title,
                                    url=url,
                                    min_chars=min_text_chars,
                                ) or (
                                    relaxed_recovery
                                    and _is_relaxed_recovery_text(text=fetched_text, title=fetched_title, url=url)
                                ):
                                    text = fetched_text
                                    title = fetched_title
                            except Exception:
                                pass

                    if not _is_substantive_rule_text(
                        text=text,
                        title=title,
                        url=url,
                        min_chars=min_text_chars,
                    ):
                        if relaxed_recovery and _is_relaxed_recovery_text(text=text, title=title, url=url):
                            pass
                        else:
                            inventory_link_bonus = 2 if inventory_page else 0
                            inventory_html_bonus = 2 if inventory_page else 1
                            inventory_rule_bonus = 4 if inventory_page else 3
                            inventory_utah_bonus = 5 if inventory_page else 4
                            for rule_url in _candidate_montana_rule_urls_from_text(
                                text=fetched_html or text,
                                url=url,
                                limit=24,
                            ):
                                if _enqueue_pending_candidate(rule_url, _score_candidate_url(rule_url) + inventory_rule_bonus):
                                    expanded_urls += 1
                            if state_code == "MT":
                                try:
                                    montana_rule_urls = await asyncio.wait_for(
                                        _discover_montana_rule_document_urls(url, limit=24),
                                        timeout=20.0,
                                    )
                                except Exception:
                                    montana_rule_urls = []
                                for rule_rank, rule_url in enumerate(montana_rule_urls):
                                    if _enqueue_pending_candidate(
                                        rule_url,
                                        _score_candidate_url(rule_url) + inventory_rule_bonus + max(0, 4 - int(rule_rank)),
                                    ):
                                        expanded_urls += 1
                            same_host = current_host if current_host in base_hosts else ""
                            for link_rank, link_url in enumerate(
                                _candidate_links_from_scrape(
                                    scraped,
                                    base_host=same_host,
                                    page_url=url,
                                    limit=8,
                                    allowed_hosts=allowed_hosts,
                                )
                            ):
                                link_score = _score_candidate_url(link_url)
                                if link_score <= 0:
                                    continue
                                depth_bonus = max(0, 6 - int(link_rank)) if inventory_page else 0
                                if _enqueue_pending_candidate(link_url, link_score + inventory_link_bonus + depth_bonus):
                                    expanded_urls += 1
                            for link_rank, link_url in enumerate(
                                _candidate_links_from_html(
                                    fetched_html,
                                    base_host=same_host,
                                    page_url=url,
                                    limit=12,
                                    allowed_hosts=allowed_hosts,
                                )
                            ):
                                link_score = _score_candidate_url(link_url)
                                if link_score <= 0:
                                    continue
                                depth_bonus = max(0, 6 - int(link_rank)) if inventory_page else 0
                                if _enqueue_pending_candidate(link_url, link_score + inventory_html_bonus + depth_bonus):
                                    expanded_urls += 1
                            for rule_url in _candidate_utah_rule_urls_from_public_api(
                                url=url,
                                limit=24,
                            ):
                                if _enqueue_pending_candidate(rule_url, _score_candidate_url(rule_url) + inventory_utah_bonus):
                                    expanded_urls += 1

                            if (
                                not official_index_page
                                and not inventory_page
                                and deep_discovery_calls < 2
                                and time.monotonic() - state_start < (per_state_budget_s * 0.8)
                            ):
                                try:
                                    deep_discovery_calls += 1
                                    deep_discovered = await asyncio.wait_for(
                                        asyncio.to_thread(
                                            lambda: unified_api.agentic_discover_and_fetch(
                                                seed_urls=[url],
                                                target_terms=_query_target_terms_for_state(state_code),
                                                max_hops=max(0, int(max_hops)),
                                                max_pages=max(2, min(8, int(max_pages))),
                                                mode=OperationMode.BALANCED,
                                                allowed_hosts=sorted(allowed_hosts),
                                                blocked_url_patterns=[_NON_ADMIN_SOURCE_URL_RE.pattern],
                                            ),
                                        ),
                                        timeout=35.0,
                                    )
                                    _record_rate_limit_metadata(deep_discovered)
                                    for fetch_row in deep_discovered.get("results", []) or []:
                                        if not isinstance(fetch_row, dict):
                                            continue
                                        _record_rate_limit_metadata(fetch_row)
                                        document = fetch_row.get("document") or {}
                                        deep_url = ""
                                        if isinstance(document, dict):
                                            deep_url = str(document.get("url") or fetch_row.get("url") or "").strip()
                                        else:
                                            deep_url = str(fetch_row.get("url") or "").strip()
                                        if not deep_url.startswith(("http://", "https://")):
                                            continue
                                        if not _url_allowed_for_state(deep_url, allowed_hosts):
                                            continue
                                        if _enqueue_pending_candidate(deep_url, _score_candidate_url(deep_url) + 1):
                                            expanded_urls += 1
                                except Exception:
                                    pass

                            continue
                    method_used = getattr(scraped, "method_used", None)
                    method_value = getattr(method_used, "value", method_used) if method_used else None
                    accepted_pending = await _append_document_if_rule(url, title, text, method_value, source_phase="pending_candidate")
                    if state_code == "AZ":
                        _record_az_phase(
                            "pending_candidate",
                            url=url,
                            outcome="success" if accepted_pending else "none",
                        )
                    if not accepted_pending:
                        continue

                    # Official rule-index pages are useful corpus rows in their own right,
                    # but they should also act as expansion hubs so the crawler can step
                    # from statewide/title indexes into deeper rule pages.
                    if inventory_page and not official_index_can_be_substantive:
                        same_host = host if host in base_hosts else urlparse(url).netloc
                        for rule_url in _candidate_montana_rule_urls_from_text(
                            text=fetched_html or text,
                            url=url,
                            limit=24,
                        ):
                            if _enqueue_pending_candidate(rule_url, _score_candidate_url(rule_url) + 4):
                                expanded_urls += 1
                        if state_code == "MT":
                            try:
                                montana_rule_urls = await asyncio.wait_for(
                                    _discover_montana_rule_document_urls(url, limit=24),
                                    timeout=20.0,
                                )
                            except Exception:
                                montana_rule_urls = []
                            for rule_rank, rule_url in enumerate(montana_rule_urls):
                                if _enqueue_pending_candidate(
                                    rule_url,
                                    _score_candidate_url(rule_url) + 4 + max(0, 4 - int(rule_rank)),
                                ):
                                    expanded_urls += 1
                        for link_url in _candidate_links_from_scrape(
                            scraped,
                            base_host=same_host,
                            page_url=url,
                            limit=24,
                            allowed_hosts=allowed_hosts,
                        ):
                            link_score = _score_candidate_url(link_url)
                            if link_score <= 0:
                                continue
                            if _enqueue_pending_candidate(link_url, link_score + 2):
                                expanded_urls += 1
                        for link_url in _candidate_links_from_html(
                            fetched_html,
                            base_host=same_host,
                            page_url=url,
                            limit=24,
                            allowed_hosts=allowed_hosts,
                        ):
                            link_score = _score_candidate_url(link_url)
                            if link_score <= 0:
                                continue
                            if _enqueue_pending_candidate(link_url, link_score + 2):
                                expanded_urls += 1
                        for rule_url in _candidate_utah_rule_urls_from_public_api(
                            url=url,
                            limit=24,
                        ):
                            if _enqueue_pending_candidate(rule_url, _score_candidate_url(rule_url) + 5):
                                expanded_urls += 1
                        pending.sort(key=_pending_candidate_sort_key)

                    if len(statutes) >= max_fetch:
                        break
                except Exception:
                    continue

            pending = sorted(pending, key=_pending_candidate_sort_key)

        state_block = {
            "state_code": state_code,
            "state_name": state_name,
            "title": f"{state_name} Administrative Rules",
            "source": "Agentic web-archive discovery",
            "source_url": seed_urls[0] if seed_urls else None,
            "scraped_at": datetime.now().isoformat(),
            "statutes": statutes,
            "rules_count": len(statutes),
            "schema_version": "1.0",
            "normalized": True,
        }
        if state_rate_limit_metadata:
            state_block.update(state_rate_limit_metadata)
        blocks.append(state_block)
        candidate_url_samples: List[str] = []
        for url, _score in ranked_urls:
            if url not in candidate_url_samples:
                candidate_url_samples.append(url)
            if len(candidate_url_samples) >= 16:
                break
        if len(candidate_url_samples) < 16:
            for url in candidate_urls:
                if url not in candidate_url_samples:
                    candidate_url_samples.append(url)
                if len(candidate_url_samples) >= 16:
                    break
        direct_detail_candidate_samples: List[str] = []
        for url, _score in pending:
            if not _is_direct_detail_candidate_url(url):
                continue
            if url in direct_detail_candidate_samples:
                continue
            direct_detail_candidate_samples.append(url)
            if len(direct_detail_candidate_samples) >= 16:
                break
        if len(direct_detail_candidate_samples) < 16:
            for url in candidate_urls:
                if not _is_direct_detail_candidate_url(url):
                    continue
                if url in direct_detail_candidate_samples:
                    continue
                direct_detail_candidate_samples.append(url)
                if len(direct_detail_candidate_samples) >= 16:
                    break
        state_elapsed_s = max(0.0, time.monotonic() - state_start)
        if state_code == "AZ":
            url_provenance = az_fetch_diagnostics.get("url_provenance")
            emitted_documents = az_fetch_diagnostics.get("emitted_documents")
            if not isinstance(emitted_documents, dict):
                emitted_documents = {}
            if isinstance(url_provenance, dict):
                for emitted_url, provenance in url_provenance.items():
                    if not isinstance(provenance, dict):
                        continue
                    accepted_phase = provenance.get("accepted_phase")
                    if not provenance.get("emitted") and not accepted_phase:
                        continue
                    emitted_entry = emitted_documents.get(emitted_url)
                    if not isinstance(emitted_entry, dict):
                        emitted_entry = {}
                        emitted_documents[emitted_url] = emitted_entry
                    emitted_entry["emitted"] = True
                    emitted_entry["source_domain"] = urlparse(emitted_url).netloc
                    if accepted_phase:
                        emitted_entry["accepted_phase"] = accepted_phase
                    accepted_format = provenance.get("accepted_format") or _document_format_for_url(emitted_url)
                    if accepted_format:
                        emitted_entry["accepted_format"] = accepted_format
                    for field_name in (
                        "accepted_method",
                        "accepted_title",
                    ):
                        field_value = provenance.get(field_name)
                        if field_value:
                            emitted_entry[field_name] = field_value
            az_fetch_diagnostics["emitted_documents"] = emitted_documents
            final_statute_sources: List[Dict[str, Any]] = []
            for statute in statutes:
                if not isinstance(statute, dict):
                    continue
                source_url = str(statute.get("source_url") or "").strip()
                if not source_url:
                    continue
                final_entry: Dict[str, Any] = {
                    "source_url": source_url,
                    "source_domain": urlparse(source_url).netloc,
                    "source_format": _document_format_for_url(source_url),
                }
                section_name = str(statute.get("section_name") or "").strip()
                if section_name:
                    final_entry["section_name"] = section_name[:200]
                section_number = str(statute.get("section_number") or "").strip()
                if section_number:
                    final_entry["section_number"] = section_number
                emitted_entry = emitted_documents.get(source_url)
                if isinstance(emitted_entry, dict):
                    accepted_phase = emitted_entry.get("accepted_phase")
                    if accepted_phase:
                        final_entry["accepted_phase"] = accepted_phase
                final_statute_sources.append(final_entry)
            az_fetch_diagnostics["final_statute_sources"] = final_statute_sources
        report[state_code] = {
            "candidate_urls": len(ranked_urls),
            "inspected_urls": int(inspected_urls),
            "inspected_url_samples": inspected_url_samples,
            "expanded_urls": int(expanded_urls),
            "fetched_rules": len(statutes),
            "vermont_lexis_signin_block_count": int(vermont_lexis_signin_block_count),
            "vermont_lexis_access_blocked": bool(vermont_lexis_access_blocked),
            "seed_urls": [url for url in seed_urls[:8]],
            "top_candidate_urls": candidate_url_samples,
            "direct_detail_candidate_samples": direct_detail_candidate_samples,
            "format_counts": dict(format_counts),
            "domains_seen": sorted(visited_hosts),
            "parallel_prefetch": {
                "attempted": int(parallel_prefetch_attempted),
                "successful": int(parallel_prefetch_succeeded),
                "rule_hits": int(parallel_prefetch_rule_hits),
            },
            "gap_summary": {
                "seed_hosts": sorted(
                    {
                        _gap_summary_host_key(url)
                        for url in seed_urls
                        if urlparse(url).netloc
                    }
                ),
                "candidate_hosts": sorted(
                    {
                        _gap_summary_host_key(url)
                        for url, _score in ranked_urls
                        if urlparse(url).netloc
                    }
                ),
                "rule_hosts": sorted(
                    {
                        _gap_summary_host_key(host)
                        for host, count in rules_by_host.items()
                        if int(count) > 0
                    }
                ),
                "missing_seed_hosts": sorted(
                    {
                        _gap_summary_host_key(url)
                        for url in seed_urls
                        if urlparse(url).netloc
                        and _gap_summary_host_key(url)
                        not in {_gap_summary_host_key(host) for host in visited_hosts}
                    }
                ),
                "candidate_hosts_without_rules": sorted(
                    {
                        _gap_summary_host_key(url)
                        for url, _score in ranked_urls
                        if urlparse(url).netloc
                        and _gap_summary_host_key(url)
                        not in {_gap_summary_host_key(host) for host, count in rules_by_host.items() if int(count) > 0}
                    }
                )[:12],
            },
            "source_breakdown": source_breakdown,
            "new_hampshire_bootstrap_diagnostics": new_hampshire_bootstrap_diagnostics if state_code == "NH" else {},
            "arizona_fetch_diagnostics": az_fetch_diagnostics if state_code == "AZ" else {},
            "timed_out": bool(state_elapsed_s >= per_state_budget_s and not statutes),
        }
        if state_fetch_cap is not None:
            report[state_code]["max_fetch_cap"] = int(state_fetch_cap)
            report[state_code]["effective_max_fetch"] = int(max_fetch)
        if state_rate_limit_metadata:
            report[state_code].update(state_rate_limit_metadata)

    return {
        "status": "success",
        "state_blocks": blocks,
        "kg_rows": kg_rows,
        "report": report,
    }


async def list_state_admin_rule_jurisdictions(include_dc: bool = False) -> Dict[str, Any]:
    """Return available state jurisdictions for admin-rules scraping.

    By default this returns the 50 US states only (excluding DC).
    Set ``include_dc=True`` to include District of Columbia.
    """
    base = await list_state_jurisdictions()
    if base.get("status") != "success":
        return base

    states = dict(base.get("states") or {})
    if not include_dc:
        states.pop("DC", None)

    return {
        "status": "success",
        "states": states,
        "count": len(states),
        "include_dc": bool(include_dc),
        "note": "Includes all 50 US states" + (" plus DC" if include_dc else ""),
    }


async def scrape_state_admin_rules(
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
    max_base_statutes: Optional[int] = None,
    per_state_timeout_seconds: float = 86400.0,
    include_dc: bool = False,
    agentic_fallback_enabled: bool = True,
    agentic_max_candidates_per_state: int = 1000,
    agentic_max_fetch_per_state: int = 1000,
    agentic_max_results_per_domain: int = 1000,
    agentic_max_hops: int = 4,
    agentic_max_pages: int = 1000,
    agentic_fetch_concurrency: int = 6,
    write_agentic_kg_corpus: bool = True,
    require_substantive_rule_text: bool = True,
) -> Dict[str, Any]:
    """Scrape state administrative rules for selected states.

    The scraper delegates network extraction to ``scrape_state_laws`` and then
    filters the normalized output to administrative-rule records only.
    """
    try:
        allowed_state_codes = set(US_STATES.keys() if include_dc else US_50_STATE_CODES)
        selected_states = [
            s.upper()
            for s in (states or [])
            if s and str(s).upper() in allowed_state_codes
        ]
        if not selected_states or "ALL" in selected_states:
            selected_states = list(US_STATES.keys() if include_dc else US_50_STATE_CODES)

        source_diagnostics = _collect_admin_source_diagnostics(selected_states)
        cloudflare_browser_rendering = _cloudflare_browser_rendering_availability()
        phase_timings: Dict[str, float] = {}

        def _record_phase(phase_name: str, started_at: float) -> None:
            phase_timings[phase_name] = round(max(0.0, time.time() - started_at), 4)

        start = time.time()
        effective_max_base_statutes = max_base_statutes
        if effective_max_base_statutes is None and max_rules and int(max_rules) > 0:
            effective_max_base_statutes = int(max_rules)

        requested_per_state_timeout_seconds = float(per_state_timeout_seconds or 0.0)
        per_state_timeout_is_unbounded = requested_per_state_timeout_seconds <= 0.0
        delegated_state_laws_timeout_seconds = (
            0.0 if per_state_timeout_is_unbounded else max(1.0, requested_per_state_timeout_seconds)
        )
        delegated_base_timeout_seconds = delegated_state_laws_timeout_seconds
        delegated_fallback_timeout_seconds = delegated_state_laws_timeout_seconds
        agentic_per_state_budget_seconds = (
            0.0
            if per_state_timeout_is_unbounded
            else max(30.0, delegated_state_laws_timeout_seconds * (2.0 / 3.0))
        )
        if delegated_state_laws_timeout_seconds > 1.0:
            delegated_base_timeout_seconds = max(15.0, delegated_state_laws_timeout_seconds * 0.5)
            delegated_fallback_timeout_seconds = max(15.0, delegated_state_laws_timeout_seconds * 0.5)

        direct_agentic_all_states = str(
            os.getenv("LEGAL_ADMIN_RULES_DIRECT_AGENTIC_ALL_STATES") or ""
        ).strip().lower() in {"1", "true", "yes", "on"}
        if direct_agentic_all_states:
            direct_agentic_states = list(selected_states)
            delegated_base_states = []
        else:
            direct_agentic_states = [
                state_code for state_code in selected_states if state_code in _DIRECT_AGENTIC_RECOVERY_STATES
            ]
            delegated_base_states = [
                state_code for state_code in selected_states if state_code not in _DIRECT_AGENTIC_RECOVERY_STATES
            ]
        if direct_agentic_states and not delegated_base_states and not per_state_timeout_is_unbounded:
            agentic_per_state_budget_seconds = max(
                agentic_per_state_budget_seconds,
                delegated_state_laws_timeout_seconds,
            )

        base_started_at = time.time()
        if delegated_base_states:
            base_result = await scrape_state_laws(
                states=delegated_base_states,
                legal_areas=["administrative"],
                output_format=output_format,
                include_metadata=include_metadata,
                rate_limit_delay=rate_limit_delay,
                max_statutes=effective_max_base_statutes,
                allow_justia_fallback=False,
                output_dir=None,  # Keep separate admin-rules output root.
                write_jsonld=False,
                strict_full_text=strict_full_text,
                min_full_text_chars=min_full_text_chars,
                hydrate_statute_text=hydrate_rule_text,
                parallel_workers=parallel_workers,
                per_state_retry_attempts=0,
                retry_zero_statute_states=False,
                per_state_timeout_seconds=delegated_base_timeout_seconds,
            )
        else:
            base_result = {
                "status": "success",
                "data": [],
                "metadata": {"states_scraped": []},
            }
        _record_phase("base_scrape_seconds", base_started_at)

        filter_started_at = time.time()
        raw_data = list(base_result.get("data") or [])
        filtered_data, admin_rule_count, zero_rule_states = _filter_admin_state_blocks(
            raw_data,
            max_rules=max_rules,
            min_full_text_chars=int(min_full_text_chars),
            require_substantive_text=bool(require_substantive_rule_text),
        )
        filtered_data, added_zero_states = _ensure_target_state_blocks(
            filtered_data,
            selected_states=selected_states,
        )
        if added_zero_states:
            zero_rule_states = sorted(set(zero_rule_states).union(added_zero_states))
        _record_phase("filter_seconds", filter_started_at)

        fallback_attempted_states: List[str] = []
        fallback_recovered_states: List[str] = []
        if retry_zero_rule_states and zero_rule_states:
            fallback_started_at = time.time()
            direct_agentic_state_set = {
                str(state_code or "").upper()
                for state_code in direct_agentic_states
                if str(state_code or "").strip()
            }
            fallback_attempted_states = sorted(
                state_code
                for state_code in set(zero_rule_states)
                if state_code not in direct_agentic_state_set
            )
            if fallback_attempted_states:
                fallback_result = await scrape_state_laws(
                    states=fallback_attempted_states,
                    legal_areas=None,
                    output_format=output_format,
                    include_metadata=include_metadata,
                    rate_limit_delay=rate_limit_delay,
                    max_statutes=effective_max_base_statutes,
                    allow_justia_fallback=False,
                    output_dir=None,
                    write_jsonld=False,
                    strict_full_text=strict_full_text,
                    min_full_text_chars=min_full_text_chars,
                    hydrate_statute_text=hydrate_rule_text,
                    parallel_workers=parallel_workers,
                    per_state_retry_attempts=0,
                    retry_zero_statute_states=False,
                    per_state_timeout_seconds=delegated_fallback_timeout_seconds,
                )

                fallback_filtered, _, _ = _filter_admin_state_blocks(
                    list(fallback_result.get("data") or []),
                    max_rules=max_rules,
                    min_full_text_chars=int(min_full_text_chars),
                    require_substantive_text=bool(require_substantive_rule_text),
                )
                fallback_by_state = {
                    str(item.get("state_code") or "").upper(): item
                    for item in fallback_filtered
                    if isinstance(item, dict)
                }

                merged: List[Dict[str, Any]] = []
                for block in filtered_data:
                    state_code = str((block or {}).get("state_code") or "").upper()
                    replacement = fallback_by_state.get(state_code)
                    if replacement and int(replacement.get("rules_count") or 0) > int(block.get("rules_count") or 0):
                        merged.append(replacement)
                        if int(block.get("rules_count") or 0) == 0:
                            fallback_recovered_states.append(state_code)
                    else:
                        merged.append(block)
                filtered_data = merged
                admin_rule_count = sum(int((item or {}).get("rules_count") or 0) for item in filtered_data)
                zero_rule_states = [
                    str(item.get("state_code") or "").upper()
                    for item in filtered_data
                    if isinstance(item, dict) and int(item.get("rules_count") or 0) == 0
                ]
            _record_phase("fallback_retry_seconds", fallback_started_at)

        agentic_attempted_states: List[str] = []
        agentic_recovered_states: List[str] = []
        agentic_report: Dict[str, Any] = {}
        agentic_rate_limit_metadata: Dict[str, Any] = {}
        agentic_rate_limited_states: List[str] = []
        agentic_browser_challenge_states: List[str] = []
        kg_corpus_jsonl: Optional[str] = None
        if agentic_fallback_enabled and zero_rule_states:
            agentic_started_at = time.time()
            agentic_attempted_states = sorted(set(zero_rule_states))
            agentic_result = await _agentic_discover_admin_state_blocks(
                states=agentic_attempted_states,
                max_candidates_per_state=int(agentic_max_candidates_per_state),
                max_fetch_per_state=int(agentic_max_fetch_per_state),
                max_results_per_domain=int(agentic_max_results_per_domain),
                max_hops=int(agentic_max_hops),
                max_pages=int(agentic_max_pages),
                min_full_text_chars=int(min_full_text_chars),
                require_substantive_text=bool(require_substantive_rule_text),
                fetch_concurrency=int(agentic_fetch_concurrency),
                per_state_budget_seconds=agentic_per_state_budget_seconds,
            )
            _record_phase("agentic_discovery_seconds", agentic_started_at)
            agentic_report = {
                "status": agentic_result.get("status"),
                "error": agentic_result.get("error"),
                "per_state": agentic_result.get("report") or {},
            }
            for state_code, state_report in (agentic_report.get("per_state") or {}).items():
                agentic_rate_limit_metadata = _merge_cloudflare_rate_limit_metadata(agentic_rate_limit_metadata, state_report)
                state_cloudflare_status = str((state_report or {}).get("cloudflare_status") or "").strip().lower()
                if state_cloudflare_status == "rate_limited":
                    agentic_rate_limited_states.append(str(state_code or "").upper())
                if state_cloudflare_status == "browser_challenge":
                    agentic_browser_challenge_states.append(str(state_code or "").upper())

            fallback_blocks = list(agentic_result.get("state_blocks") or [])
            fallback_by_state = {
                str(item.get("state_code") or "").upper(): item
                for item in fallback_blocks
                if isinstance(item, dict)
            }
            merged: List[Dict[str, Any]] = []
            for block in filtered_data:
                state_code = str((block or {}).get("state_code") or "").upper()
                replacement = fallback_by_state.get(state_code)
                if replacement and int(replacement.get("rules_count") or 0) > int(block.get("rules_count") or 0):
                    merged.append(replacement)
                    if int(block.get("rules_count") or 0) == 0:
                        agentic_recovered_states.append(state_code)
                else:
                    merged.append(block)
            filtered_data = merged

            kg_rows = list(agentic_result.get("kg_rows") or [])
            if write_agentic_kg_corpus and kg_rows:
                kg_write_started_at = time.time()
                output_root = _resolve_admin_output_dir(output_dir)
                kg_corpus_jsonl = _write_agentic_kg_corpus_jsonl(kg_rows, output_root)
                _record_phase("kg_corpus_write_seconds", kg_write_started_at)

            admin_rule_count = sum(int((item or {}).get("rules_count") or 0) for item in filtered_data)
            zero_rule_states = [
                str(item.get("state_code") or "").upper()
                for item in filtered_data
                if isinstance(item, dict) and int(item.get("rules_count") or 0) == 0
            ]

        states_with_rules = sorted(
            {
                str(item.get("state_code") or "").upper()
                for item in filtered_data
                if isinstance(item, dict) and int(item.get("rules_count") or 0) > 0
            }
        )
        _normalize_admin_rule_payloads(filtered_data)
        target_state_set = set(selected_states)
        missing_rule_states = sorted(target_state_set - set(states_with_rules))

        canonical_corpus = get_canonical_legal_corpus("state_admin_rules")
        jsonld_paths: List[str] = []
        jsonld_dir: Optional[str] = None
        if write_jsonld:
            jsonld_started_at = time.time()
            output_root = _resolve_admin_output_dir(output_dir)
            jsonld_root = canonical_corpus.jsonld_dir(str(output_root))
            jsonld_root.mkdir(parents=True, exist_ok=True)
            jsonld_paths = _write_state_admin_jsonld_files(filtered_data, jsonld_root)
            jsonld_dir = str(jsonld_root)
            _record_phase("jsonld_write_seconds", jsonld_started_at)

        elapsed = time.time() - start
        phase_timings["total_seconds"] = round(max(0.0, elapsed), 4)
        metadata = {
            "states_scraped": selected_states,
            "states_count": len(selected_states),
            "target_jurisdictions": "50_states" + ("+DC" if include_dc else ""),
            "include_dc": bool(include_dc),
            "rules_count": admin_rule_count,
            "canonical_dataset": canonical_corpus.key,
            "canonical_hf_dataset_id": canonical_corpus.hf_dataset_id,
            "elapsed_time_seconds": elapsed,
            "scraped_at": datetime.now().isoformat(),
            "scraper_type": "State admin-rules via state-specific/fallback pipeline",
            "delegated_legal_areas": ["administrative"],
            "rate_limit_delay": rate_limit_delay,
            "parallel_workers": int(parallel_workers),
            "per_state_retry_attempts": int(per_state_retry_attempts),
            "state_laws_internal_retry_attempts": 0,
            "state_laws_internal_retry_zero_statute_states": False,
            "state_laws_base_per_state_timeout_seconds": float(delegated_base_timeout_seconds),
            "state_laws_fallback_per_state_timeout_seconds": float(delegated_fallback_timeout_seconds),
            "base_scrape_skipped_states": direct_agentic_states or None,
            "direct_agentic_all_states": bool(direct_agentic_all_states),
            "agentic_per_state_budget_seconds": float(agentic_per_state_budget_seconds),
            "retry_zero_rule_states": bool(retry_zero_rule_states),
            "fallback_attempted_states": fallback_attempted_states or None,
            "fallback_recovered_states": sorted(set(fallback_recovered_states)) or None,
            "agentic_fallback_enabled": bool(agentic_fallback_enabled),
            "agentic_attempted_states": agentic_attempted_states or None,
            "agentic_recovered_states": sorted(set(agentic_recovered_states)) or None,
            "agentic_report": agentic_report or None,
            "kg_etl_corpus_jsonl": kg_corpus_jsonl,
            "agentic_max_candidates_per_state": int(agentic_max_candidates_per_state),
            "agentic_max_fetch_per_state": int(agentic_max_fetch_per_state),
            "agentic_max_results_per_domain": int(agentic_max_results_per_domain),
            "agentic_max_hops": int(agentic_max_hops),
            "agentic_max_pages": int(agentic_max_pages),
            "agentic_fetch_concurrency": int(agentic_fetch_concurrency),
            "require_substantive_rule_text": bool(require_substantive_rule_text),
            "max_base_statutes": int(effective_max_base_statutes) if effective_max_base_statutes else None,
            "per_state_timeout_seconds": float(per_state_timeout_seconds),
            "strict_full_text": bool(strict_full_text),
            "min_full_text_chars": int(min_full_text_chars),
            "hydrate_rule_text": bool(hydrate_rule_text),
            "zero_rule_states": sorted(set(zero_rule_states)) if zero_rule_states else None,
            "states_with_rules_count": len(states_with_rules),
            "states_with_rules": states_with_rules,
            "missing_rule_states_count": len(missing_rule_states),
            "missing_rule_states": missing_rule_states,
            "coverage_ratio": (len(states_with_rules) / float(len(selected_states))) if selected_states else 0.0,
            "phase_timings": phase_timings,
            "jsonld_dir": jsonld_dir,
            "jsonld_files": jsonld_paths if jsonld_paths else None,
            "base_status": base_result.get("status"),
            "base_metadata": base_result.get("metadata") if include_metadata else None,
            "source_diagnostics": source_diagnostics,
            "cloudflare_browser_rendering": cloudflare_browser_rendering,
            "cloudflare_status": agentic_rate_limit_metadata.get("cloudflare_status") if agentic_rate_limit_metadata else None,
            "retry_after_seconds": agentic_rate_limit_metadata.get("retry_after_seconds") if agentic_rate_limit_metadata else None,
            "retry_at_utc": agentic_rate_limit_metadata.get("retry_at_utc") if agentic_rate_limit_metadata else None,
            "retryable": agentic_rate_limit_metadata.get("retryable") if agentic_rate_limit_metadata else None,
            "wait_budget_exhausted": agentic_rate_limit_metadata.get("wait_budget_exhausted") if agentic_rate_limit_metadata else None,
            "rate_limit_diagnostics": agentic_rate_limit_metadata.get("rate_limit_diagnostics") if agentic_rate_limit_metadata else None,
            "cloudflare_http_status": agentic_rate_limit_metadata.get("cloudflare_http_status") if agentic_rate_limit_metadata else None,
            "cloudflare_browser_challenge_detected": agentic_rate_limit_metadata.get("cloudflare_browser_challenge_detected") if agentic_rate_limit_metadata else None,
            "cloudflare_error_excerpt": agentic_rate_limit_metadata.get("cloudflare_error_excerpt") if agentic_rate_limit_metadata else None,
            "cloudflare_record_status": agentic_rate_limit_metadata.get("cloudflare_record_status") if agentic_rate_limit_metadata else None,
            "cloudflare_job_status": agentic_rate_limit_metadata.get("cloudflare_job_status") if agentic_rate_limit_metadata else None,
            "rate_limited_states": sorted(set(agentic_rate_limited_states)) or None,
            "browser_challenge_states": sorted(set(agentic_browser_challenge_states)) or None,
        }

        status = "success"
        if base_result.get("status") in {"error", "partial_success"}:
            status = "partial_success"
        if admin_rule_count == 0 and str(metadata.get("cloudflare_status") or "").strip().lower() == "rate_limited":
            status = "rate_limited"
        elif admin_rule_count == 0:
            status = "partial_success"

        return {
            "status": status,
            "data": filtered_data,
            "metadata": metadata,
            "output_format": output_format,
        }

    except Exception as exc:
        logger.error("State administrative-rules scraping failed: %s", exc)
        return {
            "status": "error",
            "error": str(exc),
            "data": [],
            "metadata": {},
        }


__all__ = [
    "list_state_admin_rule_jurisdictions",
    "scrape_state_admin_rules",
]
