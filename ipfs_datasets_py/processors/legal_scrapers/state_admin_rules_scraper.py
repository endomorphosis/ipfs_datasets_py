"""State administrative-rules scraper orchestration.

This module reuses the state-laws scraping pipeline, then keeps only
administrative-rule records so the output corpus is focused on state
administrative rules/codes.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from html import unescape
import json
import logging
import os
import re
import time
import requests
from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from urllib.parse import quote, unquote, urljoin, urlparse

from .state_laws_scraper import (
    US_STATES,
    _get_official_state_url,
    list_state_jurisdictions,
    scrape_state_laws,
)

logger = logging.getLogger(__name__)

US_50_STATE_CODES: List[str] = [code for code in US_STATES.keys() if code != "DC"]

_ADMIN_RULE_TEXT_RE = re.compile(
    r"administrative|admin\.?\s+code|code\s+of\s+regulations|regulation|agency\s+rule|oar\b|aac\b|arc\b|nmac\b",
    re.IGNORECASE,
)

_ADMIN_LINK_HINT_RE = re.compile(
    r"administrative|admin\.?\s+code|regulation|rules?|code|statute|chapter|subchapter|part|article|section|title|agency|board|commission|"
    r"state_agencies/[\w.-]+\.html|\b[A-Za-z]{2,4}(?:-[A-Za-z]{1,3})?\s*\d{3}\b|\b\d{2}:\d{2}\b|\b\d{1,3}\.\d{1,3}(?:\.\d{1,4})?\b",
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
    r"(?:^|https?://)(?:www\.)?uscode\.house\.gov/|(?:^|https?://)(?:www\.)?ecfr\.gov/|"
    r"(?:^|https?://)(?:www\.)?le\.utah\.gov/|(?:^|https?://)(?:www\.)?legislature\.vermont\.gov/|(?:^|https?://)(?:www\.)?leg\.mt\.gov/|"
    r"(?:^|https?://)(?:www\.)?iga\.in\.gov/static-documents/(?:|$)|"
    r"(?:^|https?://)(?:www\.)?azleg\.gov/arsDetail(?:\?|/|$)|"
    r"(?:^|https?://)(?:www\.)?azleg\.gov/viewdocument(?:/viewDocument)?/\?docName=https?://(?:www\.)?azleg\.gov/ars/|"
    r"(?:^|https?://)(?:www\.)?azsos\.gov/business/notary-public(?:/|$)|"
    r"(?:^|https?://)(?:www\.)?sos\.alabama\.gov/administrative-services/(?:|$)|"
    r"(?:^|https?://)admincode\.legislature\.state\.al\.us/agency(?:/|$)|"
    r"(?:^|https?://)(?:www\.)?sdlegislature\.gov/Statutes(?:\?|/|$)|"
    r"(?:^|https?://)(?:www\.)?legislature\.mi\.gov/(?:$|rules(?:\?|/|$)|Search/ExecuteSearch|Laws/(?:MCL|ChapterIndex)(?:\?|/|$))|"
    r"(?:^|https?://)(?:www\.)?legislature\.mi\.gov/Laws/Index\?(?:[^#]*&)?ObjectName=mcl-chap|(?:^|https?://)(?:www\.)?texashuntingforum\.com/|"
    r"(?:^|https?://)(?:www\.)?rules\.sos\.ga\.gov/(?:help\.aspx|download_pdf\.aspx)|"
    r"(?:^|https?://)(?:www\.)?boardsandcommissions\.sd\.gov/",
    re.IGNORECASE,
)

_BAD_DISCOVERY_DOMAIN_RE = re.compile(
    r"(^|\.)(city-data\.com|legalclarity\.org|texashuntingforum\.com|montanaheritagecommission\.mt\.gov|wikipedia\.org|britannica\.com|ballotpedia\.org|zhihu\.com)$",
    re.IGNORECASE,
)

_BAD_DISCOVERY_TEXT_RE = re.compile(
    r"site\s+has\s+moved|redirected\s+shortly|page\s+not\s+found|404\s+not\s+found|403\s+forbidden|toggle\s+navigation|submit\s+your\s+own\s+pictures|"
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

_NON_RULE_POLICY_PAGE_RE = re.compile(
    r"department\s+of\s+corrections\s+policies|policies\s+manual|contracts\s+policies\s+procedures|"
    r"social\s+media\s+terms\s+of\s+use|state\s+hr\s+policies|policy\s+and\s+procedure\s+management",
    re.IGNORECASE,
)

_FORUM_PAGE_RE = re.compile(
    r"rules?\s+of\s+conduct|forum\s+guidelines|family\s+friendly|volunteer\s+moderators?|"
    r"moderation\s+is\s+interpretation|posting\s+privilege|signature\s+images|back\s+to\s+the\s+.*forum|"
    r"do\s+not\s+create\s+more\s+than\s+one\s+user\s+account|classifieds",
    re.IGNORECASE,
)

_VT_NON_RULE_PORTAL_PATH_RE = re.compile(
    r"/SOS/rules/(?:index\.php|search\.php|rssFeed\.php|calendar\.php|subscribe\.php|contact\.php|iCalendar\.php)$|"
    r"/secretary-of-state-services/apa-rules(?:/.*)?$",
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
    r"^/(?:public/rule/[^/]+/Current%20Rules|api/public/getHTML/[^?#]+)",
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
}

_TX_TRANSFER_INDEX_PATH_RE = re.compile(r"^/texreg/transfers(?:/|/index\.shtml)?$", re.IGNORECASE)

_MI_NON_RULE_PORTAL_PATH_RE = re.compile(r"^/(?:|home/?|admincode/admincode/?)$", re.IGNORECASE)

_RI_NON_RULE_PORTAL_PATH_RE = re.compile(r"^/organizations/?$", re.IGNORECASE)


def _prefers_live_fetch(url: str) -> bool:
    parsed = urlparse(str(url or "").strip())
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    if host in _LIVE_FETCH_PREFERRED_HOSTS:
        return True
    if host == "adminrules.utah.gov" and (
        path.startswith("/public/search") or bool(_UT_RULE_DETAIL_PATH_RE.search(parsed.path or ""))
    ):
        return True
    return False

_NH_ARCHIVED_RULE_CHAPTER_URL_RE = re.compile(
    r"^https?://web\.archive\.org/web/\d+/https?://gc\.nh\.gov/rules/state_agencies/[\w.-]+\.html$",
    re.IGNORECASE,
)

_NH_ARCHIVED_RULE_CHAPTER_TEXT_RE = re.compile(
    r"\bchapter\s+[A-Za-z-]+\s*\d{3}\b|\bpart\s+[A-Za-z-]+\s*\d{3}\b|statutory\s+authority:|\bsource\.\b",
    re.IGNORECASE,
)

_NH_ARCHIVED_RULE_PREFIX_RE = re.compile(r"\b[A-Za-z]{2,4}(?:-[A-Za-z]{1,3})?\s*\d{3}\b")

_RULE_BODY_SIGNAL_RE = re.compile(
    r"§\s*\d|\barm\s+\d|\b\d{1,3}\.\d{1,3}\.\d{1,4}\b|authority\s*:|history\s*:|implementing\s*:|"
    r"purpose\s+of\s+regulations|notice\s+of\s+adoption|notice\s+of\s+proposed\s+(?:amendment|adoption|repeal)",
    re.IGNORECASE,
)

_OFFICIAL_RULE_INDEX_URL_RE = re.compile(
    r"(?:^|https?://)(?:rules\.mt\.gov/browse/collections(?:/|$)|sdlegislature\.gov/Rules/Administrative(?:/|$)|"
    r"rules\.utah\.gov(?:/(?:utah-administrative-code|publications/(?:administrative-rules-register|code-updates))?)?(?:/|$)|"
    r"adminrules\.utah\.gov(?:/(?:public/(?:home|search)(?:/.*)?|api/public/searchRuleDataTotal/[^/]+/Current%20Rules))?(?:/|$)|"
    r"iar\.iga\.in\.gov/code(?:/(?:current|2006))?(?:/|$)|"
    r"admincode\.legislature\.state\.al\.us/(?:administrative-code|agency|search)?(?:/|$)|"
    r"azsos\.gov/rules(?:/arizona-administrative-code)?(?:/|$)|"
    r"apps\.azsos\.gov/public_services/(?:CodeTOC\.htm|Title_[\w.-]+\.htm)?$)",
    re.IGNORECASE,
)

_SD_RULE_INDEX_ROW_RE = re.compile(r"\b\d{2}:\d{2}\b")
_MT_RULE_INDEX_ROW_RE = re.compile(r"\bTitle\s+\d+\b", re.IGNORECASE)

_PDF_BINARY_HEADER_RE = re.compile(r"^\s*%PDF-\d\.\d", re.IGNORECASE)
_RTF_CONTENT_PREFIX_RE = re.compile(r"^\s*\{\\rtf", re.IGNORECASE)
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
        "https://apps.azsos.gov/public_services/Title_07/7-02.pdf",
        "https://apps.azsos.gov/public_services/Title_18/18-04.rtf",
    ],
    "AK": [
        "https://www.akleg.gov/basis/aac.asp",
        "https://ltgov.alaska.gov/information/regulations/",
        "http://akrules.elaws.us/aac",
    ],
    "AR": [
        "https://codeofarrules.arkansas.gov/",
        "https://sos-rules-reg.ark.org/",
        "https://www.sos.arkansas.gov/rules-regulations/",
        "https://ark.org/rules_and_regs/index.php/rules/search/new",
    ],
    "CA": [
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
    "LA": [
        "https://www.doa.la.gov/doa/osr/lac/",
        "https://www.doa.la.gov/doa/osr/",
        "https://www.sos.la.gov/BusinessServices/Pages/ReadAdministrativeRules.aspx",
        "https://www.sos.la.gov/ElectionsAndVoting/ReviewAdministrationAndHistory/ReadAdministrativeRules/Pages/default.aspx",
        "https://www.sos.la.gov/OurOffice/FindAdministrativeRules/Pages/default.aspx",
    ],
    "MS": [
        "https://sos.ms.gov/regulation-enforcement/administrative-code",
        "https://www.sos.ms.gov/regulation-enforcement/administrative-code",
        "https://www.sos.ms.gov/adminsearch/Pages/default.aspx",
        "https://www.sos.ms.gov/adminsearch/default.aspx",
        "https://www.sos.ms.gov/adminsearch/",
    ],
    "NH": [
        "http://web.archive.org/web/20250308091642/https://gc.nh.gov/rules/",
        "http://web.archive.org/web/20250308091642/https://gc.nh.gov/rules/about_rules/listagencies.aspx",
        "http://web.archive.org/web/20250308091642/https://gc.nh.gov/rules/about_rules/checkrule.aspx",
        "http://web.archive.org/web/20250308091642/https://gc.nh.gov/rules/state_agencies/he-p300.html",
        "http://web.archive.org/web/20250308091642/https://gc.nh.gov/rules/state_agencies/agr100.html",
        "http://web.archive.org/web/20250308091642/https://gc.nh.gov/rules/state_agencies/agr200.html",
        "http://web.archive.org/web/20250308091642/https://gc.nh.gov/rules/state_agencies/env-wq300.html",
        "http://web.archive.org/web/20250308091642/https://gc.nh.gov/rules/state_agencies/env-wq400.html",
        "http://web.archive.org/web/20250308091642/https://gc.nh.gov/rules/state_agencies/rev100.html",
        "http://web.archive.org/web/20250308091642/https://gc.nh.gov/rules/state_agencies/saf-c200.html",
        "https://gc.nh.gov/rules/state_agencies/",
        "https://gc.nh.gov/rules/",
        "https://gencourt.state.nh.us/rules/state_agencies/env-ws1101-1105.html",
        "https://www.gencourt.state.nh.us/rules/state_agencies/",
        "https://www.gencourt.state.nh.us/rules/",
    ],
    "NM": [
        "http://web.archive.org/web/20260210051847/https://www.srca.nm.gov/nmac-home/",
        "http://web.archive.org/web/20260210051847/https://www.srca.nm.gov/nmac-home/nmac-titles/",
        "https://www.srca.nm.gov/nmac-home/",
        "https://www.srca.nm.gov/nmac-home/nmac-titles/",
        "https://www.srca.nm.gov/nmac-home/explanation-of-the-new-mexico-administrative-code/",
        "https://www.srca.nm.gov/",
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
        "https://rules.mt.gov/",
        "https://sosmt.gov/arm/",
        "https://sosmt.gov/arm/secretary-of-state-administrative-rules/",
        "https://sosmt.gov/?liquid-mega-menu=arm",
        "https://rules.mt.gov/browse/collections",
        "https://rules.mt.gov/browse/collections/aec52c46-128e-4279-9068-8af5d5432d74",
        "https://rules.mt.gov/browse/collections/aec52c46-128e-4279-9068-8af5d5432d74/sections/ed446fdb-2d8d-4759-89ac-9cab3b21695c",
        "https://rules.mt.gov/browse/collections/aec52c46-128e-4279-9068-8af5d5432d74/sections/f15f6670-85c3-43bc-a946-4632329a8e23",
        "https://rules.mt.gov/browse/collections/aec52c46-128e-4279-9068-8af5d5432d74/sections/1892387a-b61e-4aa2-a1dd-d9f7a535fd42",
        "https://rules.mt.gov/browse/collections/aec52c46-128e-4279-9068-8af5d5432d74/sections/f504ae22-401c-4752-ac93-50e35903f1cd",
        "https://rules.mt.gov/search",
        "https://rules.mt.gov/browse/collections/aec52c46-128e-4279-9068-8af5d5432d74/sections/1f2ff5c5-b709-420b-bdd4-f6009ca7d33f",
        "https://rules.mt.gov/browse/collections/aec52c46-128e-4279-9068-8af5d5432d74/sections/b68c4d42-26f2-4fb4-b6a8-e1a2d4d265d2",
        "https://rules.mt.gov/browse/collections/aec52c46-128e-4279-9068-8af5d5432d74/sections/5eaf58c6-ae9f-4ebe-afe2-c617e962b390",
        "https://rules.mt.gov/browse/collections/aec52c46-128e-4279-9068-8af5d5432d74/sections/9af1b5dc-0d82-4413-bd9c-2cb707e5a8bd",
        "https://rules.mt.gov/browse/collections/aec52c46-128e-4279-9068-8af5d5432d74/sections/cd2f9808-ce8d-4a4a-b05c-fd9fa5d034e0",
        "https://rules.mt.gov/browse/collections/aec52c46-128e-4279-9068-8af5d5432d74/sections/11f11d0c-eb65-430a-baab-8728335a0c1b",
        "https://rules.mt.gov/browse/collections/aec52c46-128e-4279-9068-8af5d5432d74/sections/7e03f397-e356-4d0e-87b7-d4923e83599f",
        "https://rules.mt.gov/browse/collections/aec52c46-128e-4279-9068-8af5d5432d74/sections/c51b386c-09d3-476e-ab0b-ba97d644b619",
        "https://sosmt.gov/arm/register/",
        "https://sosmt.gov/arm/rulemaking-resources/",
    ],
    "MI": [
        "https://www.michigan.gov/lara/bureau-list/moahr/admin-rules",
        "https://ars.apps.lara.state.mi.us/AdminCode/AdminCode",
        "https://ars.apps.lara.state.mi.us/Transaction/RFRTransaction?TransactionID=1306",
        "http://mirules.elaws.us/search/allcode",
    ],
    "RI": [
        "https://www.sos.ri.gov/divisions/open-government-center/rules-and-regulations",
        "https://rules.sos.ri.gov/Organizations",
        "https://rules.sos.ri.gov/organizations/help/faq_gen-ricr",
        "https://rules.sos.ri.gov/regulations/part/510-00-00-1",
        "https://rules.sos.ri.gov/regulations/part/510-00-00-2",
        "https://rules.sos.ri.gov/regulations/part/510-00-00-3",
        "https://rules.sos.ri.gov/regulations/part/510-00-00-4",
        "https://rules.sos.ri.gov/regulations/part/510-00-00-5",
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
        "https://rules.utah.gov/utah-administrative-code/",
        "https://rules.utah.gov/publications/administrative-rules-register/",
        "https://rules.utah.gov/publications/code-updates/",
    ],
    "VT": [
        "https://secure.vermont.gov/SOS/rules/",
        "https://secure.vermont.gov/SOS/rules/index.php",
        "https://secure.vermont.gov/SOS/rules/search.php",
        "https://secure.vermont.gov/SOS/rules/rssFeed.php",
        "https://secure.vermont.gov/SOS/rules/display.php?r=1049",
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
        "https://sharetngov.tnsosfiles.com/sos/pub/tar/index.htm",
        "https://www.tn.gov/sos/rules-and-regulations.html",
    ],
    "WY": [
        "http://web.archive.org/web/20260207213344/https://rules.wyo.gov/",
        "http://web.archive.org/web/20250917082256/https://rules.wyo.gov/Search.aspx",
        "https://rules.wyo.gov/",
        "https://rules.wyo.gov/Help/Public/wyoming-administrative-rules-h.html",
        "https://rules.wyo.gov/Search.aspx",
    ],
}

# States that still need broader, controlled acceptance during recovery runs.
_RECOVERY_RELAXED_STATES = {"AL", "AZ", "HI", "MS", "MT", "NH", "SD", "TN"}


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
    return (Path.home() / ".ipfs_datasets" / "state_admin_rules").resolve()


def _build_admin_fallback_jsonld_payload(*, state_code: str, state_name: str, statute: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    full_text = str(statute.get("full_text") or "").strip()
    section_number = str(statute.get("section_number") or "").strip()
    section_name = str(statute.get("section_name") or "").strip()
    code_name = str(statute.get("code_name") or "").strip()
    source_url = str(statute.get("source_url") or "").strip()
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
    }

    if source_url:
        payload["sameAs"] = source_url
    if code_name:
        payload["legislationIdentifier"] = code_name

    return payload


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
        return [".gov"]
    return [
        f"{low}.gov",
        f"state.{low}.us",
        f"admincode.{low}.gov",
        "rules.state.us",
        ".gov",
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
    official_host = urlparse(official_url).netloc.lower().strip(".")
    if official_host:
        allowed_hosts.add(official_host)

    return {host for host in allowed_hosts if host}


def _url_allowed_for_state(url: str, allowed_hosts: set[str]) -> bool:
    host = urlparse(str(url or "").strip()).netloc.lower().strip(".")
    if not host:
        return False
    return _host_matches_allowed(host, allowed_hosts)


def _agentic_query_for_state(state_code: str) -> str:
    state_name = US_STATES.get(state_code, state_code)
    return f"{state_name} administrative code regulations agency rules"


def _extract_seed_urls_for_state(state_code: str, state_name: str) -> List[str]:
    urls: List[str] = []
    try:
        urls.extend(_STATE_ADMIN_SOURCE_MAP.get(str(state_code or "").upper(), []))

        from .state_scrapers import GenericStateScraper, get_scraper_for_state

        scraper = get_scraper_for_state(state_code, state_name)
        if scraper is None:
            scraper = GenericStateScraper(state_code, state_name)
        base_url = str(scraper.get_base_url() or "").strip()
        if base_url:
            urls.append(base_url)
        code_list = list(scraper.get_code_list() or [])
        admin_priority_urls: List[str] = []
        generic_urls: List[str] = []
        for item in code_list:
            if not isinstance(item, dict):
                continue
            code_name = str(item.get("name") or "")
            value = str(item.get("url") or "").strip()
            code_type = str(item.get("type") or "")
            if not value:
                continue
            signal = " ".join([code_name, code_type, value])
            if _ADMIN_RULE_TEXT_RE.search(signal):
                admin_priority_urls.append(value)
            else:
                generic_urls.append(value)

        # Prefer admin-specific code entrypoints, then a small generic tail.
        urls.extend(admin_priority_urls)
        urls.extend(generic_urls[:6])

        # Add deterministic admin URL templates as seed entrypoints too.
        urls.extend(_template_admin_urls_for_state(state_code))
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
        seen.add(key)
        deduped.append(value)
    return deduped[:20]


def _template_admin_urls_for_state(state_code: str) -> List[str]:
    base_url = str(_get_official_state_url(state_code) or "").strip()
    if not base_url:
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


def _score_candidate_url(url: str) -> int:
    value = str(url or "").lower()
    score = 0
    parsed = urlparse(str(url or "").strip())
    host = parsed.netloc.lower()
    path = parsed.path or ""
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
        score -= 6
    if host == "apps.azsos.gov" and _AZ_OFFICIAL_DOCUMENT_PATH_RE.search(path):
        score += 8
    return score


def _url_key(url: str) -> str:
    return str(url or "").strip().lower().rstrip("/")


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
    if re.search(r"/code/(?:current|2006)/\d+/\d+(?:\.\d+)?", lower_url):
        score += 4
        if re.search(r"\b(?:article|rule)\b", hay, re.IGNORECASE):
            score += 2

    low_text = str(link_text or "").strip()
    if low_text and _LOW_VALUE_LINK_TEXT_RE.fullmatch(low_text):
        score -= 4
    if _LOW_VALUE_LINK_URL_RE.search(str(link_url or "")):
        score -= 4
    if page_url and _url_key(link_url) == _url_key(page_url):
        score -= 5
    return score


def _build_initial_pending_candidates(
    ranked_urls: List[tuple[str, int]],
    seed_expansion_candidates: List[tuple[str, int]],
    max_candidates: int,
) -> List[tuple[str, int]]:
    pending: List[tuple[str, int]] = list(ranked_urls[:max(1, int(max_candidates))])
    pending.extend(seed_expansion_candidates)
    pending.sort(key=lambda item: item[1], reverse=True)
    return pending


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


def _is_direct_detail_candidate_url(url: str) -> bool:
    parsed = urlparse(str(url or "").strip())
    host = parsed.netloc.lower()
    path = parsed.path or ""
    if host == "adminrules.utah.gov" and _UT_RULE_DETAIL_PATH_RE.search(path):
        return True
    if host == "apps.azsos.gov" and _AZ_OFFICIAL_DOCUMENT_PATH_RE.search(path):
        return True
    return False


def _direct_detail_candidate_backlog_is_ready(candidate_urls: List[str], max_fetch: int) -> bool:
    detail_candidates = [
        (url, _score_candidate_url(url))
        for url in candidate_urls
        if _is_direct_detail_candidate_url(url)
    ]
    return _seed_expansion_backlog_is_ready(detail_candidates, max_fetch)


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

    if _NH_ARCHIVED_RULE_CHAPTER_URL_RE.search(url_value):
        nh_hay = " ".join([title_value, body])
        if _NH_ARCHIVED_RULE_CHAPTER_TEXT_RE.search(nh_hay):
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


def _looks_like_non_rule_admin_page(*, text: str, title: str, url: str) -> bool:
    hay = " ".join([str(title or ""), str(url or ""), str(text or "")])
    title_value = str(title or "").strip()
    url_value = str(url or "").strip()
    nav_hits = len(_NAVIGATION_PAGE_TOKEN_RE.findall(hay))
    parsed = urlparse(url_value)
    host = parsed.netloc.lower()
    path = parsed.path or ""
    normalized_path = path.rstrip("/") or "/"
    query = parsed.query or ""
    if _OFF_TOPIC_HISTORY_PAGE_RE.search(hay):
        return True
    if host == "ars.apps.lara.state.mi.us" and _MI_NON_RULE_PORTAL_PATH_RE.fullmatch(normalized_path):
        return True
    if host == "rules.sos.ri.gov" and _RI_NON_RULE_PORTAL_PATH_RE.fullmatch(normalized_path):
        return True
    if host in {"secure.vermont.gov", "sos.vermont.gov"} and _VT_NON_RULE_PORTAL_PATH_RE.search(path):
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
    if _NON_RULE_ADMIN_LANDING_RE.search(hay) and not _RULE_BODY_SIGNAL_RE.search(hay):
        return True
    if _NON_RULE_POLICY_PAGE_RE.search(hay):
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


def _looks_like_official_rule_index_page(*, text: str, title: str, url: str) -> bool:
    body = str(text or "").strip()
    title_value = str(title or "").strip()
    url_value = str(url or "").strip()
    if not body or not url_value:
        return False
    if not _OFFICIAL_RULE_INDEX_URL_RE.search(url_value):
        return False

    hay = " ".join([title_value, body])
    parsed = urlparse(url_value)
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    mt_title_hits = len(_MT_RULE_INDEX_ROW_RE.findall(body))
    sd_row_hits = len(_SD_RULE_INDEX_ROW_RE.findall(body))

    if "administrative rules of montana" in hay.lower() and mt_title_hits >= 5:
        return True
    if "general provisions" in hay.lower() and mt_title_hits >= 3:
        return True
    if "administrative rules" in hay.lower() and sd_row_hits >= 8:
        return True
    if "alabama administrative code" in hay.lower() and len(re.findall(r"\b(?:agency|chapter|rule|title)\b", hay, re.IGNORECASE)) >= 4:
        return True
    if "arizona administrative code" in hay.lower() and len(re.findall(r"\btitle\s+\d+\b", hay, re.IGNORECASE)) >= 4:
        return True
    if host == "iar.iga.in.gov" and "indiana administrative code" in hay.lower() and len(re.findall(r"\btitle\s+\d+(?:\.\d+)?\b", hay, re.IGNORECASE)) >= 8:
        return True
    if host in {"adminrules.utah.gov", "rules.utah.gov"} and "utah administrative code" in hay.lower() and len(re.findall(r"\b(?:code|rule|agency|administrative)\b", hay, re.IGNORECASE)) >= 4:
        return True
    if host == "adminrules.utah.gov" and path.startswith("/public/search") and "administrative rules search" in hay.lower():
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
    hay = " ".join([title_value, body])
    chapter_hits = len(re.findall(r"\bchapter\b", body, re.IGNORECASE))
    subchapter_hits = len(re.findall(r"\bsubchapter\b", body, re.IGNORECASE))
    sd_row_hits = len(_SD_RULE_INDEX_ROW_RE.findall(body))
    mt_rule_hits = len(re.findall(r"\b\d{1,3}\.\d{1,3}\.\d{2,4}\b", body))
    nh_prefix_hits = len(_NH_ARCHIVED_RULE_PREFIX_RE.findall(hay))

    if host == "rules.mt.gov" and (chapter_hits >= 3 or subchapter_hits >= 2 or mt_rule_hits >= 2):
        return True
    if host == "admincode.legislature.state.al.us" and chapter_hits >= 3:
        return True
    if host == "sdlegislature.gov" and sd_row_hits >= 8:
        return True
    if host == "web.archive.org" and "gc.nh.gov/rules" in url_value.lower() and (
        "rules listed by state agency" in hay.lower() or nh_prefix_hits >= 12
    ):
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
    body = str(text or "")
    url_value = str(url or "").strip()
    parsed = urlparse(url_value)
    if parsed.netloc.lower() != "rules.mt.gov":
        return []

    match = re.match(r"^/browse/collections/([0-9a-fA-F-]+)/sections/", parsed.path)
    if not match:
        return []

    collection_id = match.group(1)
    out: List[str] = []
    seen = set()
    for rule_id in re.findall(r"\b\d{1,2}\.\d{1,2}\.\d{2,4}\b", body):
        if rule_id in seen:
            continue
        seen.add(rule_id)
        out.append(f"https://rules.mt.gov/browse/collections/{collection_id}/rules/{rule_id}")
        if len(out) >= max(1, int(limit)):
            break
    return out


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
    elif len(path_parts) >= 6 and path_parts[:4] == ["api", "public", "searchRuleDataTotal", path_parts[3]]:
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
    if not search_term or search_term.lower() == "undefined":
        # Utah's empty search route no longer serves JSON for the legacy
        # `undefined` token, but the broad `R` query still returns the current-rule
        # index as JSON and is enough to bootstrap substantive detail pages.
        search_term = "R"

    encoded_search_term = quote(search_term, safe="")
    api_url = f"https://adminrules.utah.gov/api/public/searchRuleDataTotal/{encoded_search_term}/Current%20Rules"
    out: List[str] = []
    seen = set()

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
        return []

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
                    key = _url_key(candidate_url)
                    if key and key not in seen:
                        seen.add(key)
                        out.append(candidate_url)
                        if len(out) >= max(1, int(limit)):
                            return out
    return out


def _is_pdf_candidate_url(url: str) -> bool:
    value = str(url or "").strip().lower()
    return value.endswith(".pdf") or ".pdf?" in value


def _is_rtf_candidate_url(url: str) -> bool:
    value = str(url or "").strip().lower()
    return value.endswith(".rtf") or ".rtf?" in value


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
    value = str(match.group(1) or "").replace("%20", " ").strip()
    return value or "Current Rules"


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
    search_url = (
        "https://adminrules.utah.gov/api/public/searchRuleDataTotal/"
        f"{quote(reference_number, safe='')}/{quote(rule_type, safe='')}"
    )

    try:
        search_response = requests.get(search_url, timeout=35, headers=headers)
        search_response.raise_for_status()
        payload = search_response.json()
    except Exception:
        return None

    decoded_rule_path = unquote(parsed.path or "")
    matched_rule: Optional[Dict[str, Any]] = None
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
            html_response = requests.get(
                html_url,
                timeout=35,
                headers={**headers, "Accept": "*/*"},
            )
            html_response.raise_for_status()
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
            pdf_response = requests.get(
                pdf_url,
                timeout=35,
                headers={**headers, "Accept": "application/pdf,*/*"},
            )
            pdf_response.raise_for_status()
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
    try:
        import cloudscraper
    except Exception:
        return None

    try:
        scraper = cloudscraper.create_scraper(
            browser={"browser": "chrome", "platform": "linux", "desktop": True}
        )
        response = scraper.get(url, timeout=35, headers=_pdf_request_headers(url))
    except Exception:
        return None

    status_code = int(getattr(response, "status_code", 599) or 599)
    content_type = str(getattr(response, "headers", {}).get("content-type") or "").lower()
    body = getattr(response, "content", b"") or b""
    head = body[:1024].decode("latin1", errors="ignore")

    if status_code >= 400 or _looks_like_browser_challenge(
        status_code=status_code,
        content_type=content_type,
        head=head,
    ):
        return None
    if not body:
        return None

    return {
        "body": body,
        "content_type": content_type,
        "suggested_filename": Path(urlparse(str(url or "")).path).name,
    }


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


def _document_format_for_url(url: str) -> str:
    if _is_pdf_candidate_url(url):
        return "pdf"
    if _is_rtf_candidate_url(url):
        return "rtf"
    return "html"


async def _extract_text_from_pdf_bytes_with_processor(pdf_bytes: bytes, *, source_url: str) -> str:
    if not pdf_bytes:
        return ""

    try:
        from ipfs_datasets_py.processors.specialized.pdf import PDFProcessor
    except Exception:
        return ""

    temp_path: Optional[Path] = None
    try:
        with NamedTemporaryFile(suffix=".pdf", delete=False) as handle:
            handle.write(pdf_bytes)
            temp_path = Path(handle.name)

        processor = PDFProcessor()
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

    def _fallback_extract() -> str:
        try:
            value = rtf_bytes.decode("latin1", errors="ignore")
        except Exception:
            return ""
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
        value = re.sub(r"\\([{}\\])", r"\1", value)
        value = re.sub(r"\\[a-zA-Z]+-?\d* ?", " ", value)
        value = value.replace("{", " ").replace("}", " ")

        lines = []
        for raw_line in value.splitlines():
            cleaned = re.sub(r"\s+", " ", raw_line).strip()
            if cleaned:
                lines.append(cleaned)
        return "\n".join(lines).strip()

    try:
        from ipfs_datasets_py.processors.file_converter import RTFExtractor
    except Exception:
        return _fallback_extract()

    temp_path: Optional[Path] = None
    try:
        with NamedTemporaryFile(suffix=".rtf", delete=False) as handle:
            handle.write(rtf_bytes)
            temp_path = Path(handle.name)

        extractor = RTFExtractor()
        result = await asyncio.to_thread(extractor.extract, temp_path)
        extracted_text = str(getattr(result, "text", "") or "").strip()
        if getattr(result, "success", False) and extracted_text:
            return extracted_text
        return _fallback_extract()
    except Exception:
        return _fallback_extract()
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except Exception:
                pass


async def _scrape_pdf_candidate_url_with_processor(url: str) -> Optional[Any]:
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

    extracted_text = await _extract_text_from_pdf_bytes_with_processor(body, source_url=url)
    extracted_text = str(extracted_text or "").strip()
    if not extracted_text:
        return None

    return SimpleNamespace(
        url=url,
        title=_title_from_extracted_pdf_text(text=extracted_text, url=url),
        text=extracted_text,
        html="",
        links=[],
        success=True,
        method_used=(
            "pdf_processor_cloudscraper"
            if used_cloudscraper
            else "pdf_processor_playwright_download" if used_browser_download else "pdf_processor"
        ),
        extraction_provenance={
            "method": (
                "pdf_processor_cloudscraper"
                if used_cloudscraper
                else "pdf_processor_playwright_download" if used_browser_download else "pdf_processor"
            )
        },
    )


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


def _is_substantive_rule_text(*, text: str, title: str, url: str, min_chars: int) -> bool:
    body = str(text or "").strip()
    title_value = str(title or "").strip()
    url_value = str(url or "").strip()
    parsed = urlparse(url_value)
    host = parsed.netloc.lower()
    path = parsed.path or ""
    official_index_page = _looks_like_official_rule_index_page(text=body, title=title_value, url=url_value)
    if _has_disallowed_discovery_domain(url_value):
        return False
    if _NON_ADMIN_SOURCE_URL_RE.search(url_value):
        return False
    if _looks_like_binary_document_text(text=body, url=url_value):
        return False
    if _looks_like_forum_page(text=body, title=title_value, url=url_value):
        return False
    if _looks_like_non_rule_admin_page(text=body, title=title_value, url=url_value):
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
        if not official_index_page and not (
            pdf_like
            and len(body) >= 60
            and _has_admin_signal(text=body, title=title_value, url=url_value)
            and _LEGAL_CONTENT_SIGNAL_RE.search(" ".join([title_value, body]))
        ):
            return False
    if title_value and _looks_like_placeholder_text(title_value) and not official_index_page:
        return False
    if _looks_like_placeholder_text(body) and not official_index_page:
        return False
    if not _has_admin_signal(text=body, title=title_value, url=url_value):
        return False
    if not official_index_page and not _LEGAL_CONTENT_SIGNAL_RE.search(body):
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
    if _has_disallowed_discovery_domain(url_value):
        return False
    if _NON_ADMIN_SOURCE_URL_RE.search(url_value):
        return False
    if _looks_like_binary_document_text(text=body, url=url_value):
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
    if host == "iar.iga.in.gov" and path == "/iac":
        return False
    if host == "rules.sos.ri.gov" and path.startswith("/subscriptions"):
        return False
    if title_value and _looks_like_placeholder_text(title_value) and not official_index_page:
        return False
    if body and _looks_like_placeholder_text(body) and not official_index_page:
        return False
    if official_index_page and len(body) >= 120 and _has_admin_signal(text=body, title=title_value, url=url_value):
        return True
    if len(body) >= 80 and _has_admin_signal(text=body, title=title_value, url=url_value) and _LEGAL_CONTENT_SIGNAL_RE.search(body):
        return True
    return False


def _candidate_links_from_scrape(
    scraped: Any,
    base_host: str,
    page_url: str = "",
    limit: int = 10,
    allowed_hosts: Optional[set[str]] = None,
) -> List[str]:
    ranked: List[tuple[int, str]] = []
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
        ranked.append((score, link_url))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [link_url for _, link_url in ranked[: max(1, int(limit))]]


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
    ranked: List[tuple[int, str]] = []
    seen = set()
    for href, anchor_body in re.findall(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', body, re.IGNORECASE | re.DOTALL):
        link_url = str(href or "").strip()
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
        ranked.append((score, link_url))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [link_url for _, link_url in ranked[: max(1, int(limit))]]


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
) -> Dict[str, Any]:
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

    cfg = ScraperConfig(
        timeout=40,
        max_retries=2,
        extract_links=True,
        extract_text=True,
        fallback_enabled=True,
        rate_limit_delay=0.2,
        preferred_methods=[
            ScraperMethod.COMMON_CRAWL,
            ScraperMethod.WAYBACK_MACHINE,
            ScraperMethod.PLAYWRIGHT,
            ScraperMethod.BEAUTIFULSOUP,
            ScraperMethod.REQUESTS_ONLY,
        ],
    )
    live_cfg = ScraperConfig(
        timeout=40,
        max_retries=2,
        extract_links=True,
        extract_text=True,
        fallback_enabled=True,
        rate_limit_delay=0.2,
        preferred_methods=[
            ScraperMethod.PLAYWRIGHT,
            ScraperMethod.BEAUTIFULSOUP,
            ScraperMethod.REQUESTS_ONLY,
            ScraperMethod.WAYBACK_MACHINE,
            ScraperMethod.COMMON_CRAWL,
        ],
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
        # Keep agentic fallback bounded per state so staged runs keep moving.
        per_state_budget_s = 120.0
        state_name = US_STATES.get(state_code, state_code)
        relaxed_recovery = str(state_code or "").upper() in _RECOVERY_RELAXED_STATES
        query = _agentic_query_for_state(state_code)
        candidate_urls: List[str] = []
        source_breakdown: Dict[str, int] = {}
        allowed_hosts = _allowed_discovery_hosts_for_state(state_code, state_name)

        seed_urls = _extract_seed_urls_for_state(state_code, state_name)
        if not seed_urls:
            seed_urls = [f"https://{state_code.lower()}.gov"]

        # Always inspect curated seed entrypoints directly as ranked candidates.
        # Some states expose substantive rule indexes at the seed URL itself,
        # and agentic discovery may not re-emit that same page as a document.
        candidate_urls.extend(seed_urls)
        candidate_urls.extend(_template_admin_urls_for_state(state_code))

        utah_api_rule_urls: List[str] = []

        # Utah's public search API already exposes canonical detail-page URLs.
        # Seed them immediately so bounded runs can hit substantive rule pages
        # without waiting for slower search/index fetches to expand first.
        if state_code == "UT":
            for seed_url in seed_urls[:4]:
                for rule_url in _candidate_utah_rule_urls_from_public_api(
                    url=seed_url,
                    limit=24,
                ):
                    candidate_urls.append(rule_url)
                    utah_api_rule_urls.append(rule_url)
                    source_breakdown["utah_public_api"] = int(source_breakdown.get("utah_public_api", 0)) + 1

        seeded_direct_detail_urls = [url for url in seed_urls if _is_direct_detail_candidate_url(url)]

        direct_detail_ready = bool(utah_api_rule_urls or seeded_direct_detail_urls) or _direct_detail_candidate_backlog_is_ready(
            candidate_urls,
            max_fetch=max_fetch_per_state,
        )

        if not direct_detail_ready:
            try:
                archive_results = await legal_archive._search_archives_multi_domain(
                    query=query,
                    domains=_agentic_domains_for_state(state_code),
                    max_results_per_domain=max(1, int(max_results_per_domain)),
                )
                for row in (archive_results or {}).get("results", []) or []:
                    if not isinstance(row, dict):
                        continue
                    url = str(row.get("url") or "").strip()
                    if not url or not _url_allowed_for_state(url, allowed_hosts):
                        continue
                    candidate_urls.append(url)
                    source_breakdown["archives"] = int(source_breakdown.get("archives", 0)) + 1
            except Exception:
                pass

            try:
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
                    timeout=40.0,
                )
                for hit in getattr(unified_search, "results", []) or []:
                    url = str(getattr(hit, "url", "") or "").strip()
                    if not url or not _url_allowed_for_state(url, allowed_hosts):
                        continue
                    candidate_urls.append(url)
                    source_breakdown["search"] = int(source_breakdown.get("search", 0)) + 1
            except Exception:
                pass

        if (time.monotonic() - state_start) >= per_state_budget_s:
            report[state_code] = {
                "candidate_urls": 0,
                "inspected_urls": 0,
                "expanded_urls": 0,
                "fetched_rules": 0,
                "source_breakdown": source_breakdown,
                "timed_out": True,
            }
            blocks.append(
                {
                    "state_code": state_code,
                    "state_name": state_name,
                    "title": f"{state_name} Administrative Rules",
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

        # Curated seeds often already expose substantive rule pages or article/part
        # links. Prefetch them before broad agentic discovery so states like Indiana
        # and Rhode Island can short-circuit expensive exploration when the official
        # entrypoints are already sufficient.
        preseed_signal = direct_detail_ready
        if not direct_detail_ready:
            for seed_url in seed_urls[:6]:
                host = urlparse(seed_url).netloc
                fetch_api = live_fetch_api if _prefers_live_fetch(seed_url) else direct_fetch_api
                try:
                    fetched = await asyncio.wait_for(
                        asyncio.to_thread(
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
                    fetched_doc = getattr(fetched, "document", None)
                    fetched_text = str(getattr(fetched_doc, "text", "") or "").strip()
                    fetched_title = str(getattr(fetched_doc, "title", "") or "").strip()
                    fetched_html = str(getattr(fetched_doc, "html", "") or "")
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

                    if seed_is_substantive or seed_is_relaxed or inventory_seed:
                        preseed_signal = True
                        source_breakdown["seed_prefetch"] = int(source_breakdown.get("seed_prefetch", 0)) + 1

                    if inventory_seed:
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
                except Exception:
                    pass

        discovered: Dict[str, Any] = {}
        if not preseed_signal:
            try:
                discovered = await asyncio.wait_for(
                    asyncio.to_thread(
                        lambda: unified_api.agentic_discover_and_fetch(
                            seed_urls=seed_urls,
                            target_terms=["administrative", "regulations", "rules", "code"],
                            max_hops=max(0, int(max_hops)),
                            max_pages=max(1, int(max_pages)),
                            mode=OperationMode.BALANCED,
                        ),
                    ),
                    timeout=70.0,
                )
                for fetch_row in discovered.get("results", []) or []:
                    if not isinstance(fetch_row, dict):
                        continue
                    document = fetch_row.get("document") or {}
                    if isinstance(document, dict):
                        url = str(document.get("url") or fetch_row.get("url") or "").strip()
                    else:
                        url = str(fetch_row.get("url") or "").strip()
                    if not url or not _url_allowed_for_state(url, allowed_hosts):
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

        statutes: List[Dict[str, Any]] = []
        direct_doc_urls: set[str] = set()
        seed_expansion_candidates: List[tuple[str, int]] = []
        rules_by_host: Dict[str, int] = defaultdict(int)
        format_counts: Dict[str, int] = {"html": 0, "pdf": 0, "rtf": 0}
        visited_hosts: set[str] = set()
        parallel_prefetch_attempted = 0
        parallel_prefetch_succeeded = 0
        parallel_prefetch_rule_hits = 0
        max_fetch = max(1, int(max_fetch_per_state))
        min_text_chars = max(140, int(min_full_text_chars // 2))
        if require_substantive_text:
            min_text_chars = max(220, int(min_full_text_chars))
        effective_fetch_concurrency = max(1, int(fetch_concurrency))
        preloop_budget_deadline = state_start + max(12.0, min(45.0, per_state_budget_s * 0.25))

        async def _append_document_if_rule(doc_url: str, doc_title: str, doc_text: str, method_value: Any = None) -> bool:
            if not doc_url.startswith(("http://", "https://")):
                return False
            if not _url_allowed_for_state(doc_url, allowed_hosts):
                return False
            if not _is_substantive_rule_text(
                text=doc_text,
                title=doc_title,
                url=doc_url,
                min_chars=min_text_chars,
            ):
                if not (relaxed_recovery and _is_relaxed_recovery_text(text=doc_text, title=doc_title, url=doc_url)):
                    return False
            doc_key = _url_key(doc_url)
            if doc_key in direct_doc_urls:
                return False
            direct_doc_urls.add(doc_key)
            host_value = urlparse(doc_url).netloc.lower()
            if host_value:
                visited_hosts.add(host_value)
                rules_by_host[host_value] += 1
            doc_format = _document_format_for_url(doc_url)
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
            return True

        prefetch_candidates = [
            url
            for url, score in ranked_urls
            if int(score) > 0 and _url_key(url) not in direct_doc_urls
        ][: max(2, min(max_candidates_per_state, max_fetch * 3, effective_fetch_concurrency * 4))]

        if prefetch_candidates and time.monotonic() < preloop_budget_deadline:
            parallel_prefetch_attempted = len(prefetch_candidates)
            try:
                archived_results = await asyncio.wait_for(
                    parallel_archiver.archive_urls_parallel(prefetch_candidates),
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
                )
                if accepted_prefetch:
                    parallel_prefetch_rule_hits += 1
                if _looks_like_rule_inventory_page(text=archived_content, title=archived_title, url=archived_url):
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
                        seed_expansion_candidates.append((link_url, link_score + 1))
                        expanded_urls += 1

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

        prioritized_seed_document_urls: List[str] = []
        seen_seed_document_keys: set[str] = set()
        for seed_url in seed_urls:
            if not _is_direct_detail_candidate_url(seed_url):
                continue
            doc_key = _url_key(seed_url)
            if not doc_key or doc_key in seen_seed_document_keys:
                continue
            seen_seed_document_keys.add(doc_key)
            prioritized_seed_document_urls.append(seed_url)
            if len(prioritized_seed_document_urls) >= min(max_fetch, 8):
                break

        for rule_url in prioritized_utah_seed_rule_urls:
            if len(statutes) >= max_fetch:
                break
            if (time.monotonic() - state_start) >= per_state_budget_s:
                break
            if time.monotonic() >= preloop_budget_deadline:
                break
            try:
                utah_scraped = await asyncio.wait_for(
                    _scrape_utah_rule_detail_via_public_download(rule_url),
                    timeout=25.0,
                )
            except Exception:
                utah_scraped = None
            if utah_scraped is None:
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

        for document_url in prioritized_seed_document_urls:
            if len(statutes) >= max_fetch:
                break
            if (time.monotonic() - state_start) >= per_state_budget_s:
                break
            if time.monotonic() >= preloop_budget_deadline:
                break
            remaining_prefetch_budget_s = preloop_budget_deadline - time.monotonic()
            if remaining_prefetch_budget_s <= 1.0:
                break
            try:
                direct_scraped = await asyncio.wait_for(
                    _scrape_pdf_candidate_url_with_processor(document_url),
                    timeout=max(1.0, min(12.0, remaining_prefetch_budget_s)),
                )
            except Exception:
                direct_scraped = None
            if direct_scraped is None:
                remaining_prefetch_budget_s = preloop_budget_deadline - time.monotonic()
                if remaining_prefetch_budget_s <= 1.0:
                    break
                try:
                    direct_scraped = await asyncio.wait_for(
                        _scrape_rtf_candidate_url_with_processor(document_url),
                        timeout=max(1.0, min(12.0, remaining_prefetch_budget_s)),
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
            await _append_document_if_rule(document_url, direct_title, direct_text, direct_method_value)

        # Give curated/official entrypoints one deterministic direct fetch pass.
        for seed_url in seed_urls[:6]:
            if len(statutes) >= max(1, int(max_fetch_per_state)):
                break
            if time.monotonic() >= preloop_budget_deadline:
                break
            if _seed_expansion_backlog_is_ready(seed_expansion_candidates, max_fetch):
                break
            host = urlparse(seed_url).netloc
            fetch_api = live_fetch_api if _prefers_live_fetch(seed_url) else direct_fetch_api
            try:
                fetched = await asyncio.wait_for(
                    asyncio.to_thread(
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
                fetched_doc = getattr(fetched, "document", None)
                fetched_text = str(getattr(fetched_doc, "text", "") or "").strip()
                fetched_title = str(getattr(fetched_doc, "title", "") or "").strip()
                fetched_html = str(getattr(fetched_doc, "html", "") or "")
                method_value = None
                if fetched_doc is not None:
                    method_value = (getattr(fetched_doc, "extraction_provenance", {}) or {}).get("method")
                accepted_seed = await _append_document_if_rule(seed_url, fetched_title, fetched_text, method_value)
                inventory_seed = _looks_like_rule_inventory_page(text=fetched_text, title=fetched_title, url=seed_url)
                if inventory_seed:
                    for rule_url in _candidate_montana_rule_urls_from_text(
                        text=fetched_text,
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
                        seed_scrape_text = str(getattr(seed_scrape, "text", "") or "").strip()
                        seed_scrape_title = str(getattr(seed_scrape, "title", "") or "").strip()
                        seed_scrape_html = str(getattr(seed_scrape, "html", "") or "")
                        live_method_value = None
                        seed_scrape_provenance = getattr(seed_scrape, "extraction_provenance", None) or {}
                        if isinstance(seed_scrape_provenance, dict):
                            live_method_value = seed_scrape_provenance.get("method")
                        await _append_document_if_rule(seed_url, seed_scrape_title, seed_scrape_text, live_method_value)
                        for rule_url in _candidate_montana_rule_urls_from_text(
                            text=seed_scrape_text,
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
                if _seed_expansion_backlog_is_ready(seed_expansion_candidates, max_fetch):
                    break
            except Exception:
                pass

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
                    if not await _append_document_if_rule(doc_url, doc_title, doc_text, method_value):
                        continue
                    if len(statutes) >= max(1, int(max_fetch_per_state)):
                        break
        except Exception:
            pass

        # Montana's `rules.mt.gov` host is often easier to traverse from Common Crawl
        # than from repeated origin fetches. Supplement the candidate pool with an
        # archive-first domain scrape before the bounded live crawl loop runs.
        if state_code == "MT" and len(statutes) < min(max(1, int(max_fetch_per_state)), 12):
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
                        text=cc_text,
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

        max_candidates = max(1, int(max_candidates_per_state))
        pending = _build_initial_pending_candidates(
            ranked_urls=ranked_urls,
            seed_expansion_candidates=seed_expansion_candidates,
            max_candidates=max_candidates,
        )
        seen_urls = set(direct_doc_urls)
        inspected_urls = 0
        expanded_urls = 0
        deep_discovery_calls = 0
        base_hosts = {
            urlparse(str(seed).strip()).netloc
            for seed in seed_urls
            if str(seed).strip().startswith(("http://", "https://"))
        }
        prioritized_seed_keys = {_url_key(url) for url in seed_urls}

        async def _scrape_candidate_url(url: str):
            utah_scraped = await _scrape_utah_rule_detail_via_public_download(url)
            if utah_scraped is not None:
                return utah_scraped
            pdf_scraped = await _scrape_pdf_candidate_url_with_processor(url)
            if pdf_scraped is not None:
                return pdf_scraped
            rtf_scraped = await _scrape_rtf_candidate_url_with_processor(url)
            if rtf_scraped is not None:
                return rtf_scraped
            host = urlparse(url).netloc
            active_scraper = live_scraper if (_url_key(url) in prioritized_seed_keys or host in base_hosts) else scraper
            return await active_scraper.scrape(url)

        while pending and len(statutes) < max_fetch and inspected_urls < max(4, max_candidates * 4):
            if (time.monotonic() - state_start) >= per_state_budget_s:
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
                    text = str(getattr(scraped, "text", "") or "").strip()
                    title = str(getattr(scraped, "title", "") or "").strip()
                    fetched_html = ""
                    official_index_page = _looks_like_official_rule_index_page(text=text, title=title, url=url)

                    if not _is_substantive_rule_text(
                        text=text,
                        title=title,
                        url=url,
                        min_chars=min_text_chars,
                    ):
                        # Dynamic official rule indexes can render as a thin JS shell through
                        # the lightweight scraper even when the fuller fetch path has real text.
                        host = urlparse(url).netloc
                        if _url_key(url) in prioritized_seed_keys or host in base_hosts:
                            fetch_api = live_fetch_api if _prefers_live_fetch(url) else direct_fetch_api
                            try:
                                fetched = await asyncio.wait_for(
                                    asyncio.to_thread(
                                        fetch_api.fetch,
                                        UnifiedFetchRequest(
                                            url=url,
                                            timeout_seconds=35,
                                            mode=OperationMode.BALANCED,
                                            domain=".gov" if host.endswith(".gov") else "legal",
                                        ),
                                    ),
                                    timeout=40.0,
                                )
                                fetched_doc = getattr(fetched, "document", None)
                                fetched_text = str(getattr(fetched_doc, "text", "") or "").strip()
                                fetched_title = str(getattr(fetched_doc, "title", "") or "").strip()
                                fetched_html = str(getattr(fetched_doc, "html", "") or "")
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
                            for rule_url in _candidate_montana_rule_urls_from_text(
                                text=text,
                                url=url,
                                limit=24,
                            ):
                                pending.append((rule_url, _score_candidate_url(rule_url) + 3))
                                expanded_urls += 1
                            same_host = host if host in base_hosts else ""
                            for link_url in _candidate_links_from_scrape(
                                scraped,
                                base_host=same_host,
                                page_url=url,
                                limit=8,
                                allowed_hosts=allowed_hosts,
                            ):
                                link_score = _score_candidate_url(link_url)
                                if link_score <= 0:
                                    continue
                                pending.append((link_url, link_score))
                                expanded_urls += 1
                            for link_url in _candidate_links_from_html(
                                fetched_html,
                                base_host=same_host,
                                page_url=url,
                                limit=12,
                                allowed_hosts=allowed_hosts,
                            ):
                                link_score = _score_candidate_url(link_url)
                                if link_score <= 0:
                                    continue
                                pending.append((link_url, link_score + 1))
                                expanded_urls += 1
                            for rule_url in _candidate_utah_rule_urls_from_public_api(
                                url=url,
                                limit=24,
                            ):
                                pending.append((rule_url, _score_candidate_url(rule_url) + 4))
                                expanded_urls += 1

                            if deep_discovery_calls < 2 and time.monotonic() - state_start < (per_state_budget_s * 0.8):
                                try:
                                    deep_discovery_calls += 1
                                    deep_discovered = await asyncio.wait_for(
                                        asyncio.to_thread(
                                            lambda: unified_api.agentic_discover_and_fetch(
                                                seed_urls=[url],
                                                target_terms=["administrative", "regulation", "rule", "code", "title", "chapter"],
                                                max_hops=max(0, int(max_hops)),
                                                max_pages=max(2, min(8, int(max_pages))),
                                                mode=OperationMode.BALANCED,
                                            ),
                                        ),
                                        timeout=35.0,
                                    )
                                    for fetch_row in deep_discovered.get("results", []) or []:
                                        if not isinstance(fetch_row, dict):
                                            continue
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
                                        pending.append((deep_url, _score_candidate_url(deep_url) + 1))
                                        expanded_urls += 1
                                except Exception:
                                    pass

                            continue
                    method_used = getattr(scraped, "method_used", None)
                    method_value = getattr(method_used, "value", method_used) if method_used else None
                    if not await _append_document_if_rule(url, title, text, method_value):
                        continue

                    # Official rule-index pages are useful corpus rows in their own right,
                    # but they should also act as expansion hubs so the crawler can step
                    # from statewide/title indexes into deeper rule pages.
                    if _looks_like_rule_inventory_page(text=text, title=title, url=url):
                        same_host = host if host in base_hosts else urlparse(url).netloc
                        for rule_url in _candidate_montana_rule_urls_from_text(
                            text=text,
                            url=url,
                            limit=24,
                        ):
                            pending.append((rule_url, _score_candidate_url(rule_url) + 4))
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
                            pending.append((link_url, link_score + 2))
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
                            pending.append((link_url, link_score + 2))
                            expanded_urls += 1
                        for rule_url in _candidate_utah_rule_urls_from_public_api(
                            url=url,
                            limit=24,
                        ):
                            pending.append((rule_url, _score_candidate_url(rule_url) + 5))
                            expanded_urls += 1
                        pending.sort(key=lambda item: item[1], reverse=True)

                    if len(statutes) >= max_fetch:
                        break
                except Exception:
                    continue

            pending = sorted(pending, key=lambda item: item[1], reverse=True)

        blocks.append(
            {
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
        )
        report[state_code] = {
            "candidate_urls": len(ranked_urls),
            "inspected_urls": int(inspected_urls),
            "expanded_urls": int(expanded_urls),
            "fetched_rules": len(statutes),
            "format_counts": dict(format_counts),
            "domains_seen": sorted(visited_hosts),
            "parallel_prefetch": {
                "attempted": int(parallel_prefetch_attempted),
                "successful": int(parallel_prefetch_succeeded),
                "rule_hits": int(parallel_prefetch_rule_hits),
            },
            "gap_summary": {
                "seed_hosts": sorted({urlparse(url).netloc.lower() for url in seed_urls if urlparse(url).netloc}),
                "candidate_hosts": sorted({urlparse(url).netloc.lower() for url, _score in ranked_urls if urlparse(url).netloc}),
                "rule_hosts": sorted([host for host, count in rules_by_host.items() if int(count) > 0]),
                "missing_seed_hosts": sorted(
                    {
                        urlparse(url).netloc.lower()
                        for url in seed_urls
                        if urlparse(url).netloc and urlparse(url).netloc.lower() not in visited_hosts
                    }
                ),
                "candidate_hosts_without_rules": sorted(
                    {
                        urlparse(url).netloc.lower()
                        for url, _score in ranked_urls
                        if urlparse(url).netloc and rules_by_host.get(urlparse(url).netloc.lower(), 0) == 0
                    }
                )[:12],
            },
            "source_breakdown": source_breakdown,
            "timed_out": bool((time.monotonic() - state_start) >= per_state_budget_s),
        }

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
    per_state_timeout_seconds: float = 480.0,
    include_dc: bool = False,
    agentic_fallback_enabled: bool = True,
    agentic_max_candidates_per_state: int = 12,
    agentic_max_fetch_per_state: int = 5,
    agentic_max_results_per_domain: int = 20,
    agentic_max_hops: int = 1,
    agentic_max_pages: int = 8,
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

        start = time.time()
        effective_max_base_statutes = max_base_statutes
        if effective_max_base_statutes is None and max_rules and int(max_rules) > 0:
            effective_max_base_statutes = int(max_rules)

        base_result = await scrape_state_laws(
            states=selected_states,
            legal_areas=["administrative"],
            output_format=output_format,
            include_metadata=include_metadata,
            rate_limit_delay=rate_limit_delay,
            max_statutes=effective_max_base_statutes,
            output_dir=None,  # Keep separate admin-rules output root.
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

        fallback_attempted_states: List[str] = []
        fallback_recovered_states: List[str] = []
        if retry_zero_rule_states and zero_rule_states:
            fallback_attempted_states = sorted(set(zero_rule_states))
            fallback_result = await scrape_state_laws(
                states=fallback_attempted_states,
                legal_areas=None,
                output_format=output_format,
                include_metadata=include_metadata,
                rate_limit_delay=rate_limit_delay,
                max_statutes=effective_max_base_statutes,
                output_dir=None,
                write_jsonld=False,
                strict_full_text=strict_full_text,
                min_full_text_chars=min_full_text_chars,
                hydrate_statute_text=hydrate_rule_text,
                parallel_workers=parallel_workers,
                per_state_retry_attempts=per_state_retry_attempts,
                retry_zero_statute_states=False,
                per_state_timeout_seconds=per_state_timeout_seconds,
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

        agentic_attempted_states: List[str] = []
        agentic_recovered_states: List[str] = []
        agentic_report: Dict[str, Any] = {}
        kg_corpus_jsonl: Optional[str] = None
        if agentic_fallback_enabled and zero_rule_states:
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
            )
            agentic_report = {
                "status": agentic_result.get("status"),
                "error": agentic_result.get("error"),
                "per_state": agentic_result.get("report") or {},
            }

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
                output_root = _resolve_admin_output_dir(output_dir)
                kg_corpus_jsonl = _write_agentic_kg_corpus_jsonl(kg_rows, output_root)

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
        target_state_set = set(selected_states)
        missing_rule_states = sorted(target_state_set - set(states_with_rules))

        jsonld_paths: List[str] = []
        jsonld_dir: Optional[str] = None
        if write_jsonld:
            output_root = _resolve_admin_output_dir(output_dir)
            jsonld_root = output_root / "state_admin_rules_jsonld"
            jsonld_root.mkdir(parents=True, exist_ok=True)
            jsonld_paths = _write_state_admin_jsonld_files(filtered_data, jsonld_root)
            jsonld_dir = str(jsonld_root)

        elapsed = time.time() - start
        metadata = {
            "states_scraped": selected_states,
            "states_count": len(selected_states),
            "target_jurisdictions": "50_states" + ("+DC" if include_dc else ""),
            "include_dc": bool(include_dc),
            "rules_count": admin_rule_count,
            "elapsed_time_seconds": elapsed,
            "scraped_at": datetime.now().isoformat(),
            "scraper_type": "State admin-rules via state-specific/fallback pipeline",
            "delegated_legal_areas": ["administrative"],
            "rate_limit_delay": rate_limit_delay,
            "parallel_workers": int(parallel_workers),
            "per_state_retry_attempts": int(per_state_retry_attempts),
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
            "jsonld_dir": jsonld_dir,
            "jsonld_files": jsonld_paths if jsonld_paths else None,
            "base_status": base_result.get("status"),
            "base_metadata": base_result.get("metadata") if include_metadata else None,
            "source_diagnostics": source_diagnostics,
        }

        status = "success"
        if base_result.get("status") in {"error", "partial_success"}:
            status = "partial_success"
        if admin_rule_count == 0:
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
