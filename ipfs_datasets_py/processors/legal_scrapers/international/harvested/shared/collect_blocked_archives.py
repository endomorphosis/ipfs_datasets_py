#!/usr/bin/env python3
"""Collect blocked EU gazettes via archive fallbacks (Wayback / Common Crawl / archive.is / HTTP).

Prefer archived official HTML/XML consolidations. Never uses cylaw.org.
Resume-safe. Does not start/duplicate collect_pl/dk/at/ie/fi/mt/lv/ee/sk/hu or collect_eurlex.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (  # noqa: E402
    ROOT,
    base_record,
    corpus_bytes,
    ensure_dirs,
    existing_ids,
    html_to_text,
    iso_date,
    log_failure,
    slug_id,
    utcnow,
    write_instrument,
    write_summary,
    xml_to_text,
)
from archive_fallbacks import (  # noqa: E402
    fetch_with_fallbacks,
    has_brave_key,
    is_spa_shell,
    search_common_crawl,
    search_wayback_machine,
)

log = logging.getLogger("blocked_archives")

MAX_CDX = 2500
MAX_FETCH = 0  # fetch ALL unique official URLs
MIN_TEXT = 280
ASSET_RE = re.compile(r"\.(?:css|js|gif|png|jpg|jpeg|svg|woff2?|ico|map)(?:$|\?)", re.I)
CHROME_PATH_RE = re.compile(
    r"(?:/blog(?:/|$)|/cat_|/efhmerida/(?:polisi|diathesi|sfalmata)|/eservices|"
    r"/home/?$|/index\.html?$|/contact|/about|/cookies|/privacy|"
    r"/login|/search/?$|/favicon|/css/|/js/|/static/|/design/)",
    re.I,
)
CYLAW_RE = re.compile(r"cylaw\.org", re.I)


def clean_url(url: str) -> str:
    if not url:
        return url
    url = url.replace("http://www.ejustice.just.fgov.be:80", "http://www.ejustice.just.fgov.be")
    url = url.replace(":80/", "/")
    url = unquote(url)
    url = url.replace("\n", "").replace("\r", "").replace("\x0b", "")
    url = re.sub(r";jsessionid=[^?#]*", "", url, flags=re.I)
    url = re.sub(r"%0[AaDd]|%0B", "", url)
    url = re.sub(r"[\t\f]+", "", url).replace(" ", "%20")
    # LU: prefer JO HTML/XML over RDF negotiation
    if "data.legilux.public.lu/eli/" in url and "format=" in url:
        url = re.sub(r"\?.*$", "", url)
    return url.strip()


SPECS = {
    "be": {
        "country": "Belgium",
        "lang": "fr",
        "source_type": "justel",
        "license": (
            "Moniteur belge / Belgisch Staatsblad official publications. "
            "Justel consolidations are informational (not authentic). "
            "https://www.ejustice.just.fgov.be/eli/"
        ),
        "hosts": ("ejustice.just.fgov.be",),
        "cdx": [
            {"url": "www.ejustice.just.fgov.be/eli/constitution*", "limit": 400},
            {"url": "www.ejustice.just.fgov.be/cgi_loi/article.pl*", "limit": MAX_CDX},
            {"url": "www.ejustice.just.fgov.be/cgi_loi/change_lg.pl*", "limit": MAX_CDX},
            {"url": "www.ejustice.just.fgov.be/cgi_loi/loi_a1.pl*", "limit": 600},
            {"url": "www.ejustice.just.fgov.be/eli/loi/*", "limit": MAX_CDX},
            {"url": "www.ejustice.just.fgov.be/eli/wet/*", "limit": MAX_CDX},
            {"url": "www.ejustice.just.fgov.be/eli/decret/*", "limit": MAX_CDX},
            {"url": "www.ejustice.just.fgov.be/eli/ordonnance/*", "limit": 800},
            {"url": "www.ejustice.just.fgov.be/eli/arrete/*", "limit": MAX_CDX},
            {"url": "www.ejustice.just.fgov.be/eli/loi/1990*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/loi/1991*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/loi/1992*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/loi/1993*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/loi/1994*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/loi/1995*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/loi/1996*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/loi/1997*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/loi/1998*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/loi/1999*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/loi/2000*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/loi/2001*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/loi/2002*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/loi/2003*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/loi/2004*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/loi/2005*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/loi/2006*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/loi/2007*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/loi/2008*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/loi/2009*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/loi/2010*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/loi/2011*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/loi/2012*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/loi/2013*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/loi/2014*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/loi/2015*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/loi/2016*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/loi/2017*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/loi/2018*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/loi/2019*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/loi/2020*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/loi/2021*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/loi/2022*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/loi/2023*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/loi/2024*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/loi/2025*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/loi/2026*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/loi/1804*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/loi/1831*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/loi/1865*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/loi/1873*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/loi/1881*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/wet/1990*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/wet/1991*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/wet/1992*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/wet/1993*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/wet/1994*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/wet/1995*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/wet/1996*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/wet/1997*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/wet/1998*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/wet/1999*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/wet/2000*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/wet/2001*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/wet/2002*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/wet/2003*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/wet/2004*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/wet/2005*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/wet/2006*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/wet/2007*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/wet/2008*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/wet/2009*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/wet/2010*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/wet/2011*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/wet/2012*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/wet/2013*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/wet/2014*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/wet/2015*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/wet/2016*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/wet/2017*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/wet/2018*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/wet/2019*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/wet/2020*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/wet/2021*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/wet/2022*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/wet/2023*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/wet/2024*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/wet/2025*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/wet/2026*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/wet/1804*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/wet/1831*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/wet/1865*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/wet/1873*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/wet/1881*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/decret/1990*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/decret/1991*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/decret/1992*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/decret/1993*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/decret/1994*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/decret/1995*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/decret/1996*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/decret/1997*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/decret/1998*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/decret/1999*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/decret/2000*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/decret/2001*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/decret/2002*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/decret/2003*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/decret/2004*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/decret/2005*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/decret/2006*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/decret/2007*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/decret/2008*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/decret/2009*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/decret/2010*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/decret/2011*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/decret/2012*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/decret/2013*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/decret/2014*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/decret/2015*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/decret/2016*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/decret/2017*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/decret/2018*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/decret/2019*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/decret/2020*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/decret/2021*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/decret/2022*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/decret/2023*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/decret/2024*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/decret/2025*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/decret/2026*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/decret/1804*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/decret/1831*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/decret/1865*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/decret/1873*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/decret/1881*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/decreet/1990*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/decreet/1991*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/decreet/1992*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/decreet/1993*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/decreet/1994*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/decreet/1995*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/decreet/1996*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/decreet/1997*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/decreet/1998*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/decreet/1999*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/decreet/2000*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/decreet/2001*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/decreet/2002*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/decreet/2003*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/decreet/2004*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/decreet/2005*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/decreet/2006*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/decreet/2007*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/decreet/2008*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/decreet/2009*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/decreet/2010*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/decreet/2011*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/decreet/2012*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/decreet/2013*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/decreet/2014*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/decreet/2015*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/decreet/2016*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/decreet/2017*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/decreet/2018*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/decreet/2019*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/decreet/2020*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/decreet/2021*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/decreet/2022*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/decreet/2023*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/decreet/2024*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/decreet/2025*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/decreet/2026*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/decreet/1804*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/decreet/1831*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/decreet/1865*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/decreet/1873*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/decreet/1881*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/ordonnance/1990*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/ordonnance/1991*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/ordonnance/1992*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/ordonnance/1993*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/ordonnance/1994*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/ordonnance/1995*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/ordonnance/1996*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/ordonnance/1997*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/ordonnance/1998*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/ordonnance/1999*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/ordonnance/2000*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/ordonnance/2001*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/ordonnance/2002*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/ordonnance/2003*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/ordonnance/2004*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/ordonnance/2005*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/ordonnance/2006*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/ordonnance/2007*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/ordonnance/2008*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/ordonnance/2009*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/ordonnance/2010*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/ordonnance/2011*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/ordonnance/2012*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/ordonnance/2013*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/ordonnance/2014*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/ordonnance/2015*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/ordonnance/2016*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/ordonnance/2017*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/ordonnance/2018*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/ordonnance/2019*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/ordonnance/2020*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/ordonnance/2021*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/ordonnance/2022*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/ordonnance/2023*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/ordonnance/2024*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/ordonnance/2025*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/ordonnance/2026*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/ordonnance/1804*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/ordonnance/1831*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/ordonnance/1865*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/ordonnance/1873*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/ordonnance/1881*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/arrete/1990*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/arrete/1991*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/arrete/1992*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/arrete/1993*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/arrete/1994*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/arrete/1995*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/arrete/1996*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/arrete/1997*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/arrete/1998*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/arrete/1999*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/arrete/2000*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/arrete/2001*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/arrete/2002*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/arrete/2003*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/arrete/2004*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/arrete/2005*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/arrete/2006*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/arrete/2007*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/arrete/2008*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/arrete/2009*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/arrete/2010*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/arrete/2011*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/arrete/2012*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/arrete/2013*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/arrete/2014*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/arrete/2015*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/arrete/2016*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/arrete/2017*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/arrete/2018*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/arrete/2019*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/arrete/2020*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/arrete/2021*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/arrete/2022*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/arrete/2023*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/arrete/2024*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/arrete/2025*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/arrete/2026*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/arrete/1804*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/arrete/1831*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/arrete/1865*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/arrete/1873*", "limit": 200},
            {"url": "www.ejustice.just.fgov.be/eli/arrete/1881*", "limit": 200},
        ],
        "path_re": re.compile(r"/eli/(loi|wet|decret|decreet|ordonnance|ordonnantie|arrete|besluit|constitution|grondwet)/|/cgi_loi/", re.I),
        "require_re": re.compile(r"/justel(?:$|[/?#])|article\.pl|change_lg\.pl|loi_a1\.pl", re.I),
        "seeds": [
            "http://www.ejustice.just.fgov.be/eli/constitution/1994/02/17/1994021048/justel",
            "http://www.ejustice.just.fgov.be/eli/loi/1804/03/21/1804032150/justel",
        ],
    },
    "it": {
        "country": "Italy",
        "lang": "it",
        "source_type": "normattiva",
        "license": "Normattiva / Gazzetta Ufficiale official Italian legislation. Reuse per publisher terms.",
        "hosts": ("normattiva.it", "gazzettaufficiale.it"),
        "cdx": [
            "www.normattiva.it/uri-res/N2Ls",
            "www.gazzettaufficiale.it/eli/id/",
            "www.normattiva.it/atto/caricaDettaglioAtto",
        ],
        "path_re": re.compile(r"uri-res/N2Ls|gazzettaufficiale\.it/eli/|/atto/|/do/atto/", re.I),
        "seeds": [
            "https://www.normattiva.it/uri-res/N2Ls?urn:nir:stato:costituzione:1947-12-27",
            "https://www.gazzettaufficiale.it/eli/id/1947/12/27/047U0001/sg",
        ],
    },
    "cz": {
        "country": "Czechia",
        "lang": "cs",
        "source_type": "e_sbirka",
        "license": "e-Sbírka / Sbírka zákonů official. Open data typically not copyrighted (NKOD terms).",
        "hosts": ("e-sbirka.cz", "aplikace.mvcr.cz", "www.e-sbirka.cz"),
        "cdx": [
            "aplikace.mvcr.cz/sbirka-zakonu/ViewFile.aspx*",
            "www.e-sbirka.cz/sb/",
            "www.e-sbirka.cz/cs/detail/",
        ],
        "path_re": re.compile(r"ViewFile\.aspx|e-sbirka\.cz/(?:sb|cs/detail)|/eli/cz/", re.I),
        "seeds": [
            "https://www.e-sbirka.cz/",
            "https://aplikace.mvcr.cz/sbirka-zakonu/",
        ],
    },
    "lt": {
        "country": "Lithuania",
        "lang": "lt",
        "source_type": "etar",
        "license": "TAR / e-tar.lt official legal acts. Open-data slice often CC BY 4.0 on data.gov.lt.",
        "hosts": ("e-tar.lt", "www.e-tar.lt"),
        "cdx": [
            "www.e-tar.lt/portal/lt/legalAct/",
            "www.e-tar.lt/portal/legalAct.html",
        ],
        "path_re": re.compile(r"/legalAct", re.I),
        "seeds": [
            "https://www.e-tar.lt/portal/lt/legalAct/TAR.EC4DC009E86D",
        ],
    },
    "lu": {
        "country": "Luxembourg",
        "lang": "fr",
        "source_type": "legilux",
        "license": "data.legilux.public.lu: Creative Commons Attribution 4.0 (CC BY 4.0).",
        "hosts": ("legilux.public.lu", "data.legilux.public.lu"),
        "cdx": [
            "data.legilux.public.lu/eli/etat/leg/loi/",
            "data.legilux.public.lu/eli/etat/leg/code/",
            "legilux.public.lu/eli/etat/leg/loi/",
            "data.legilux.public.lu/file/",
        ],
        "path_re": re.compile(r"/eli/etat/leg/|/file/", re.I),
        "seeds": [
            "http://data.legilux.public.lu/eli/etat/leg/code/constitution/jo",
            "http://legilux.public.lu/eli/etat/leg/code/constitution",
        ],
    },
    "pt": {
        "country": "Portugal",
        "lang": "pt",
        "source_type": "dre",
        "license": "Diário da República (dre.pt) official gazette. Reuse per dre.pt legal notice.",
        "hosts": ("dre.pt", "data.dre.pt", "diariodarepublica.pt"),
        "cdx": [
            "dre.pt/application/conteudo/",
            "dre.pt/dre/detalhe/",
            "data.dre.pt/eli/",
            "diariodarepublica.pt/dr/detalhe/lei/",
            "diariodarepublica.pt/dr/detalhe/decreto-lei/",
        ],
        "path_re": re.compile(r"/application/conteudo/|/dre/detalhe/|/eli/|/dr/detalhe/", re.I),
        "seeds": [
            "https://dre.pt/dre/detalhe/decreto-aprovacao-constituicao/1976-480623",
            "https://data.dre.pt/eli/dec-lei/47344/1966/p/cons/20170803/pt/html",
        ],
    },
    "hr": {
        "country": "Croatia",
        "lang": "hr",
        "source_type": "narodne_novine",
        "license": "Narodne novine official gazette. Crawlers welcome; max 3 q/s on live origin.",
        "hosts": ("narodne-novine.nn.hr", "nn.hr"),
        "cdx": [
            "narodne-novine.nn.hr/clanci/sluzbeni/1990*",
            "narodne-novine.nn.hr/clanci/sluzbeni/2001*",
            "narodne-novine.nn.hr/clanci/sluzbeni/2015*",
            "narodne-novine.nn.hr/clanci/sluzbeni/2020*",
            "narodne-novine.nn.hr/eli/sluzbeni/",
        ],
        "path_re": re.compile(r"/clanci/sluzbeni/|/eli/sluzbeni/", re.I),
        "seeds": [
            "https://narodne-novine.nn.hr/clanci/sluzbeni/1990_12_56_1092.html",
        ],
    },
    "si": {
        "country": "Slovenia",
        "lang": "sl",
        "source_type": "pisrs",
        "license": "PISRS / Uradni list RS official consolidations. https://www.pisrs.si/",
        "hosts": ("pisrs.si", "uradni-list.si", "www.pisrs.si", "www.uradni-list.si"),
        "cdx": [
            "www.pisrs.si/Pis.web/pregledPredpisa",
            "www.uradni-list.si/glasilo-uradni-list-rs/vsebina/",
        ],
        "path_re": re.compile(r"pregledPredpisa|uradni-list\.si/.*/vsebina/", re.I),
        "require_re": re.compile(r"[?&]id=|vsebina/", re.I),
        "seeds": [
            "https://www.pisrs.si/Pis.web/pregledPredpisa?id=USTA1",
        ],
    },
    "ro": {
        "country": "Romania",
        "lang": "ro",
        "source_type": "legislatie_just",
        "license": "legislatie.just.ro official portal of the Ministry of Justice.",
        "hosts": ("legislatie.just.ro",),
        "cdx": [
            "legislatie.just.ro/Public/DetaliiDocument/",
            "legislatie.just.ro/Public/DetaliiDocumentAfis/",
        ],
        "path_re": re.compile(r"DetaliiDocument", re.I),
        "seeds": [
            "https://legislatie.just.ro/Public/DetaliiDocument/1",
        ],
    },
    "bg": {
        "country": "Bulgaria",
        "lang": "bg",
        "source_type": "dv_parliament",
        "license": "State Gazette of the Republic of Bulgaria (dv.parliament.bg).",
        "hosts": ("dv.parliament.bg",),
        "cdx": [
            "dv.parliament.bg/DVWeb/showMaterialDV.jsp",
            "dv.parliament.bg/DVWeb/index.faces",
        ],
        "path_re": re.compile(r"showMaterialDV|actPreview|DVWeb", re.I),
        "require_re": re.compile(r"idMat=\d+", re.I),
        "seeds": [
            "https://dv.parliament.bg/DVWeb/showMaterialDV.jsp?idMat=1",
        ],
    },
    "cy": {
        "country": "Cyprus",
        "lang": "el",
        "source_type": "official_gazette",
        "license": "Official Gazette of the Republic of Cyprus (Government Printing Office / MoF GPO). cylaw.org is unofficial and is NOT used.",
        "hosts": ("mof.gov.cy", "cyprus.gov.cy", "mof.gov.cy"),
        "cdx": [
            "www.mof.gov.cy/mof/gpo/gazette.nsf/",
            "www.mof.gov.cy/mof/gpo/gpo.nsf/",
        ],
        "path_re": re.compile(r"mof\.gov\.cy/mof/gpo|gpo\.nsf|gazette\.nsf|efimerida", re.I),
        "seeds": [
            "http://www.mof.gov.cy/mof/gpo/gpo.nsf/index_gr/index_gr",
            "https://www.mof.gov.cy/mof/gpo/gpo.nsf/dmlindex_en/dmlindex_en",
        ],
        "forbid": CYLAW_RE,
    },
    "gr": {
        "country": "Greece",
        "lang": "el",
        "source_type": "et_gr",
        "license": "National Printing Office (Εθνικό Τυπογραφείο) et.gr official gazette.",
        "hosts": ("et.gr", "www.et.gr", "search.et.gr"),
        "cdx": [
            "www.et.gr/idocs-nph/search/dllTxtDoc.html*",
            "www.et.gr/idocs-nph/search/pdfViewerForm.html*",
        ],
        "path_re": re.compile(r"idocs-nph|dllTxtDoc|pdfView|/fek/", re.I),
        "seeds": [
            "https://www.et.gr/idocs-nph/search/pdfViewerForm.html",
        ],
    },
}


def setup_log(cc: str) -> None:
    ensure_dirs(cc)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[
            logging.FileHandler(ROOT / cc / "logs" / "archive_collector.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
        force=True,
    )


def host_ok(url: str, spec: dict) -> bool:
    if spec.get("forbid") and spec["forbid"].search(url):
        return False
    if CYLAW_RE.search(url):
        return False
    host = (urlparse(url).hostname or "").lower().lstrip("www.")
    allowed = tuple(h.lower().lstrip("www.") for h in spec["hosts"])
    return any(host == a or host.endswith("." + a) for a in allowed)


def path_ok(url: str, spec: dict) -> bool:
    if CHROME_PATH_RE.search(urlparse(url).path or "/"):
        # still allow gazette article paths that happen to end with index
        if spec["path_re"].search(url):
            return True
        return False
    return bool(spec["path_re"].search(url))


def ident_from_url(cc: str, url: str) -> str:
    p = urlparse(url)
    path = unquote(p.path or "")
    q = parse_qs(p.query)
    if cc == "be":
        m = re.search(r"/eli/([^/]+)/(\d{4})/(\d{2})/(\d{2})/([0-9A-Za-z]+)", path)
        if m:
            return f"{m.group(1)}-{m.group(2)}{m.group(3)}{m.group(4)}-{m.group(5)}"
        cn = (q.get("cn") or q.get("cn_search") or q.get("view_numac") or q.get("numac") or [None])[0]
        if cn:
            cn = re.sub(r"[^0-9A-Za-z]", "", str(cn))[:20]
            if "article" in path:
                return f"article-{cn}"
            return f"cn-{cn}"
    if cc == "it":
        if "urn:nir:" in (p.query or url):
            urn = unquote(p.query.split("urn:nir:", 1)[-1] if "urn:nir:" in (p.query or "") else url)
            urn = urn.replace("urn:nir:", "")
            return "nir-" + re.sub(r"[^a-zA-Z0-9._-]+", "-", urn)[:120]
        m = re.search(r"/eli/id/(\d{4}/\d{2}/\d{2}/[^/]+)", path)
        if m:
            return "eli-" + m.group(1).replace("/", "-")
    if cc == "lt":
        m = re.search(r"/legalAct/([^/?#]+)", path)
        if m:
            return m.group(1)
        if q.get("documentId"):
            return q["documentId"][0]
    if cc == "lu":
        m = re.search(r"/eli/etat/leg/(.+)$", path)
        if m:
            return m.group(1).replace("/", "-")
    if cc == "pt":
        m = re.search(r"/conteudo/(\d+)", path)
        if m:
            return m.group(1)
        m = re.search(r"/detalhe/([^/]+)/(\d+)", path)
        if m:
            return f"{m.group(1)}-{m.group(2)}"
        m = re.search(r"/eli/(.+)$", path)
        if m:
            return m.group(1).replace("/", "-")
    if cc == "hr":
        m = re.search(r"/clanci/sluzbeni/([^/?#]+)", path)
        if m:
            return m.group(1).replace(".html", "")
        m = re.search(r"/eli/sluzbeni/(.+)$", path)
        if m:
            return m.group(1).replace("/", "-")
    if cc == "si":
        if q.get("id"):
            return q["id"][0]
        m = re.search(r"/vsebina/(.+)$", path)
        if m:
            return m.group(1).replace("/", "-")
    if cc == "ro":
        m = re.search(r"DetaliiDocument(?:Afis)?/(\d+)", path)
        if m:
            return m.group(1)
    if cc == "bg":
        if q.get("idMat"):
            return q["idMat"][0]
    if cc == "cz":
        if q.get("id"):
            return q["id"][0]
        m = re.search(r"/(?:sb|detail)/([^/?#]+)", path)
        if m:
            return m.group(1)
    if cc == "gr":
        for k in ("fek", "id", "issue"):
            if q.get(k):
                return q[k][0]
        tail = path.strip("/").replace("/", "-")
        if tail:
            return tail[-80:]
    if cc == "cy":
        tail = path.strip("/").replace("/", "-")
        if p.query:
            tail += "-" + re.sub(r"[^A-Za-z0-9]+", "-", p.query)[:40]
        return tail[-100:] or "gazette"
    tail = (path.strip("/") or p.netloc).replace("/", "-")
    return tail[-120:] or "instrument"


def date_from_url_or_ts(url: str, ts: str) -> str | None:
    m = re.search(r"(19|20)\d{2}[-/](0[1-9]|1[0-2])[-/](0[1-9]|[12]\d|3[01])", url)
    if m:
        return iso_date(m.group(0).replace("/", "-"))
    m = re.search(r"(19|20)\d{2}(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])", url)
    if m:
        return iso_date(m.group(0))
    if ts and len(ts) >= 8:
        return iso_date(ts[:8])
    return None


def extract_title(html: str, ident: str) -> str:
    if not html:
        return ident
    m = re.search(r"<title[^>]*>([^<]+)</title>", html, re.I)
    if m:
        t = re.sub(r"\s+", " ", m.group(1)).strip()
        t = re.sub(r"\s*\|\s*Wayback Machine$", "", t)
        t = re.sub(r"^Wayback Machine\s*", "", t)
        if 8 < len(t) < 300:
            return t
    for pat in (r"<h1[^>]*>([^<]{8,240})</h1>", r"<h2[^>]*>([^<]{8,240})</h2>"):
        m = re.search(pat, html, re.I)
        if m:
            return re.sub(r"\s+", " ", m.group(1)).strip()
    return ident


def pdf_to_text(blob: bytes) -> str:
    if not blob or blob[:4] != b"%PDF":
        return ""
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(blob)
            path = tmp.name
        try:
            p = subprocess.run(
                ["pdftotext", "-layout", "-nopgbrk", path, "-"],
                capture_output=True,
                timeout=40,
            )
            if p.returncode == 0:
                return (p.stdout or b"").decode("utf-8", "replace").strip()
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass
    except Exception:
        return ""
    return ""


def body_to_text(payload: dict) -> tuple[str, str]:
    ctype = (payload.get("content_type") or "").lower()
    raw_bytes = payload.get("content") or b""
    html = payload.get("text") or ""
    if isinstance(raw_bytes, str):
        raw_bytes = raw_bytes.encode("utf-8", "replace")
    if "pdf" in ctype or (raw_bytes[:4] == b"%PDF"):
        return pdf_to_text(raw_bytes), "pdf"
    if "xml" in ctype or (html.lstrip().startswith("<?xml") or "<akoma" in html[:500].lower()):
        return xml_to_text(html) or html_to_text(html), "xml"
    if html:
        return html_to_text(html), "html"
    if raw_bytes:
        try:
            return html_to_text(raw_bytes.decode("utf-8", "replace")), "bytes"
        except Exception:
            return "", "unknown"
    return "", "unknown"


def discover(cc: str, spec: dict) -> tuple[list[dict], list[str]]:
    notes = []
    hits: dict[str, dict] = {}

    def consider(url: str, meta: dict) -> None:
        url = clean_url(url or "")
        if not url or not url.startswith("http"):
            return
        if ASSET_RE.search(url):
            return
        if not host_ok(url, spec):
            return
        if not path_ok(url, spec) and url not in spec.get("seeds", []):
            return
        req = spec.get("require_re")
        if req and not req.search(url) and url not in spec.get("seeds", []):
            return
        # skip bare directories / empty query
        path = urlparse(url).path or ""
        if path.endswith("/") and not urlparse(url).query and path.count("/") < 4:
            return
        key = re.sub(r"#.*$", "", url).rstrip("/")
        if cc == "be":
            key = slug_id(cc, ident_from_url(cc, url))
        prev = hits.get(key)
        ts = str(meta.get("timestamp") or "")
        if prev and str(prev.get("timestamp") or "") >= ts:
            return
        hits[key] = {**meta, "original": url, "key": key}

    for seed in spec.get("seeds") or []:
        consider(seed, {"timestamp": "", "source": "seed", "mimetype": "text/html"})

    cc_prefixes = []
    for prefix in spec["cdx"]:
        if isinstance(prefix, dict):
            url = prefix["url"]
            lim = prefix.get("limit", MAX_CDX)
            from_date = prefix.get("from_date") or ("19900101" if cc == "be" else "20000101")
            to_date = prefix.get("to_date")
            extra = prefix.get("extra_filters")
        else:
            url = prefix
            lim = MAX_CDX
            from_date = "19900101" if cc == "be" else "20000101"
            to_date = None
            extra = None
        qurl = url if "*" in url else url + "*"
        wb = search_wayback_machine(
            qurl,
            limit=lim,
            collapse="urlkey",
            from_date=from_date,
            to_date=to_date,
            extra_filters=extra,
        )
        notes.append(f"wayback CDX {url} n={len(wb)}")
        log.info("%s wayback %s n=%s", cc, url, len(wb))
        for rec in wb:
            consider(rec.get("original") or "", rec)
        # CC only on a few broad prefixes (not per-year shards)
        if (
            len(cc_prefixes) < 6
            and not re.search(r"/\d{4}\*$", url)
            and any(k in url for k in ("/eli/loi/*", "/eli/wet/*", "/eli/decret/*", "/cgi_loi/article.pl", "/eli/arrete/*"))
        ):
            cc_prefixes.append(url)
            cc_hits = search_common_crawl(qurl, limit=200)
            notes.append(f"common_crawl CDX {url} n={len(cc_hits)}")
            log.info("%s cc %s n=%s", cc, url, len(cc_hits))
            for rec in cc_hits:
                consider(rec.get("original") or rec.get("url") or "", rec)

    items = list(hits.values())
    # prefer instrument-like long paths, then recent timestamps
    items.sort(key=lambda r: (str(r.get("timestamp") or ""), len(r.get("original") or "")), reverse=True)
    notes.append(f"unique instrument URLs={len(items)} brave_skipped={not has_brave_key()}")
    return items, notes


def fetch_one(cc: str, spec: dict, rec: dict, done: set[str]) -> str:
    url = rec.get("original") or ""
    ident = ident_from_url(cc, url)
    rid = slug_id(cc, ident)
    if rid in done:
        return "skip"
    payload = fetch_with_fallbacks(
        url,
        cc_record=rec if rec.get("filename") or rec.get("warc_filename") else None,
        wayback_ts=rec.get("timestamp") or None,
        try_archive_is=(rec.get("source") == "seed"),
        try_http=(cc != "be"),
    )
    method = payload.get("method") or "http"
    if payload.get("status") != "success":
        log_failure(cc, {"identifier": ident, "source_url": url, "status": "failed",
                         "reason": payload.get("error"), "method_used": method})
        return "fail"
    text, backend = body_to_text(payload)
    html = payload.get("text") or ""
    if cc == "be":
        if re.search(r"tspd_|bobcmn|TSPD", html or "", re.I):
            log_failure(cc, {"identifier": ident, "source_url": url, "status": "failed",
                             "reason": "tspd_shell", "method_used": method})
            return "fail"
        if "Aide ELI" in (text or "") and "requête que vous avez formulée" in (text or ""):
            log_failure(cc, {"identifier": ident, "source_url": url, "status": "failed",
                             "reason": "eli_help_page", "method_used": method})
            return "fail"
        if "Texte" not in (html or "") and "Art." not in (text or "") and "Artikel" not in (text or "") and len(text) < 1200:
            log_failure(cc, {"identifier": ident, "source_url": url, "status": "failed",
                             "reason": "empty_or_chrome", "method_used": method, "n": len(text)})
            return "fail"
    if is_spa_shell(html, text) or len(text) < MIN_TEXT:
        # LU/PT: try XML sibling
        xml_try = None
        if cc == "lu" and "/eli/" in url and not url.endswith("/xml"):
            xml_try = url.rstrip("/") + "/xml"
        if xml_try:
            alt = fetch_with_fallbacks(xml_try, wayback_ts=rec.get("timestamp") or None, try_http=True)
            if alt.get("status") == "success":
                t2, b2 = body_to_text(alt)
                if len(t2) >= MIN_TEXT:
                    payload, text, backend, method = alt, t2, b2, alt.get("method") or method
                    url = xml_try
        if len(text) < MIN_TEXT:
            log_failure(cc, {"identifier": ident, "source_url": url, "status": "failed",
                             "reason": "empty_or_chrome", "method_used": method, "n": len(text)})
            return "fail"
    title = extract_title(html, ident)
    src = payload.get("wayback_url") or payload.get("archive_url") or payload.get("final_url") or url
    rec_out = base_record(
        cc=cc,
        country=spec["country"],
        language=spec["lang"],
        ident=ident,
        title=title,
        text=text,
        source_url=url,
        source_type=spec["source_type"],
        license_text=spec["license"],
        collector=f"{cc}-archive-fallback",
        eli=url if "/eli/" in url else None,
        date=date_from_url_or_ts(url, str(rec.get("timestamp") or payload.get("capture_timestamp") or "")),
        official_identifier=ident,
        document_type="statute",
        law_status="unknown",
        is_current=None,
        extra_meta={
            "method_used": method,
            "discovery": {
                "method": rec.get("source") or "cdx",
                "seed_url": url,
                "catalog_identifier": rec.get("timestamp") or rec.get("filename") or "",
            },
            "text_extraction": {"source": "archive", "backend": backend},
            "http_status": payload.get("http_status"),
            "content_type": payload.get("content_type"),
            "archive_url": payload.get("wayback_url") or payload.get("archive_url"),
            "capture_timestamp": payload.get("capture_timestamp") or rec.get("timestamp"),
        },
    )
    rec_out["canonical_document_url"] = src
    rec_out["information_url"] = url
    write_instrument(cc, rec_out)
    done.add(rid)
    return "ok"


def harvest(cc: str) -> None:
    spec = SPECS[cc]
    setup_log(cc)
    t0 = utcnow()
    done = existing_ids(cc)
    items, notes = discover(cc, spec)
    if len(items) > MAX_FETCH:
        notes.append(f"capped fetch {MAX_FETCH} of {len(items)}")
        items = items[:MAX_FETCH]
    ok = skip = fail = 0
    methods = {}
    for i, rec in enumerate(items, 1):
        try:
            st = fetch_one(cc, spec, rec, done)
        except Exception as exc:
            st = "fail"
            log_failure(cc, {"source_url": rec.get("original"), "status": "failed", "reason": repr(exc)})
            log.exception("fetch fail")
        ok += st == "ok"
        skip += st == "skip"
        fail += st == "fail"
        if i % 15 == 0 or i == len(items):
            log.info("%s progress %s/%s ok=%s skip=%s fail=%s", cc, i, len(items), ok, skip, fail)
            write_summary(
                cc,
                country=spec["country"],
                source="archive fallbacks (wayback|common_crawl|archive_is|http)",
                source_urls=list(spec["cdx"]),
                license_text=spec["license"],
                discovered=len(items),
                fetched=ok,
                skipped=skip,
                failed=fail,
                coverage="shard" if ok else "catalog-backed incomplete",
                notes="\n".join(notes),
                last_run=utcnow(),
            )
    nbytes = corpus_bytes(cc)
    notes.append(f"method_used recorded per record in metadata.method_used")
    notes.append(f"brave_search skipped (no API key)" if not has_brave_key() else "brave_search unused")
    notes.append(f"started {t0} instruments_bytes={nbytes}")
    if ok == 0:
        notes.append("No instrument-quality snapshots after CDX+fetch (empty CDX or chrome-only).")
    write_summary(
        cc,
        country=spec["country"],
        source="archive fallbacks (wayback|common_crawl|archive_is|http)",
        source_urls=list(spec["cdx"]) + list(spec.get("seeds") or []),
        license_text=spec["license"],
        discovered=len(items),
        fetched=ok,
        skipped=skip,
        failed=fail,
        coverage="shard" if ok else "empty CDX or chrome-only",
        notes="\n".join(notes),
        last_run=utcnow(),
        extra=f"blocker_origin documented previously; this run uses archives first. ok={ok} fail={fail} skip={skip}",
    )
    log.info("%s DONE disc=%s ok=%s skip=%s fail=%s bytes=%s", cc, len(items), ok, skip, fail, nbytes)


def main():
    targets = [a for a in sys.argv[1:] if a in SPECS] or list(SPECS)
    for cc in targets:
        try:
            harvest(cc)
        except Exception:
            log.exception("country %s crashed", cc)
            spec = SPECS[cc]
            write_summary(
                cc,
                country=spec["country"],
                source="archive fallbacks",
                source_urls=spec["cdx"],
                license_text=spec["license"],
                discovered=0,
                fetched=0,
                skipped=0,
                failed=1,
                coverage="catalog-backed incomplete",
                notes="collector exception; see archive_collector.log",
                last_run=utcnow(),
            )


if __name__ == "__main__":
    main()
