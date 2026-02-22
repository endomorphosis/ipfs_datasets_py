"""
PubMed Medical Literature Scraper Engine.

Canonical business logic for scraping medical literature from PubMed.
This module is the authoritative location for the PubMedScraper class.

Exposed in ``ipfs_datasets_py.scrapers.medical`` so the same class can be used
from package imports, CLI tools, and MCP server tools.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from xml.etree import ElementTree as ET

import requests

logger = logging.getLogger(__name__)


class PubMedScraper:
    """Scraper for PubMed medical literature database.

    Collects medical research articles, clinical studies, and biochemical
    research with multiple fallback mechanisms for reliability.

    Args:
        api_key: NCBI E-utilities API key for higher rate limits.
        email: Email for NCBI E-utilities (required by NCBI TOS).
        use_fallback: Enable fallback mechanisms if primary fails.
        cache_dir: Directory for caching scraped data.

    Example::

        scraper = PubMedScraper(email="researcher@example.com")
        results = scraper.search_medical_research("COVID-19 treatment", max_results=100)
        biochem = scraper.scrape_biochemical_research(topic="protein folding")
    """

    EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
    PUBMED_FTP = "ftp://ftp.ncbi.nlm.nih.gov/pubmed/"

    def __init__(
        self,
        api_key: Optional[str] = None,
        email: Optional[str] = None,
        use_fallback: bool = True,
        cache_dir: Optional[str] = None,
    ) -> None:
        self.api_key = api_key
        self.email = email
        self.use_fallback = use_fallback
        self.cache_dir = cache_dir
        self.session = requests.Session()

        if not email:
            logger.warning("No email provided — NCBI requires an email for API access")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_eutils_params(self, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Build base E-utilities parameters."""
        params: Dict[str, Any] = {}
        if self.email:
            params["email"] = self.email
        if self.api_key:
            params["api_key"] = self.api_key
        if extra:
            params.update(extra)
        return params

    def _fetch_article_details(self, pmids: List[str]) -> List[Dict[str, Any]]:
        """Fetch detailed information for a list of PubMed IDs."""
        if not pmids:
            return []

        fetch_url = f"{self.EUTILS_BASE}efetch.fcgi"
        params = self._build_eutils_params(
            {"db": "pubmed", "id": ",".join(pmids), "retmode": "xml"}
        )

        response = self.session.get(fetch_url, params=params, timeout=60)
        response.raise_for_status()

        root = ET.fromstring(response.content)
        articles = []
        for article_elem in root.findall(".//PubmedArticle"):
            article_data = self._parse_article_xml(article_elem)
            if article_data:
                articles.append(article_data)
        return articles

    def _parse_article_xml(self, article_elem: ET.Element) -> Optional[Dict[str, Any]]:
        """Parse individual article XML element to extract metadata."""
        try:
            medline = article_elem.find(".//MedlineCitation")
            if medline is None:
                return None

            pmid_elem = medline.find(".//PMID")
            pmid = pmid_elem.text if pmid_elem is not None else None

            article = medline.find(".//Article")
            if article is None:
                return None

            title_elem = article.find(".//ArticleTitle")
            title = title_elem.text if title_elem is not None else "No title"

            abstract_parts = article.findall(".//AbstractText")
            abstract = " ".join([a.text or "" for a in abstract_parts])

            authors = []
            for author in article.findall(".//Author"):
                last_name = author.find(".//LastName")
                fore_name = author.find(".//ForeName")
                if last_name is not None and fore_name is not None:
                    authors.append(f"{fore_name.text} {last_name.text}")

            pub_date = article.find(".//PubDate")
            year = pub_date.find(".//Year") if pub_date is not None else None
            month = pub_date.find(".//Month") if pub_date is not None else None
            day = pub_date.find(".//Day") if pub_date is not None else None

            date_str = ""
            if year is not None:
                date_str = year.text or ""
                if month is not None:
                    date_str += f"-{month.text}"
                    if day is not None:
                        date_str += f"-{day.text}"

            journal_elem = article.find(".//Journal/Title")
            journal = journal_elem.text if journal_elem is not None else "Unknown"

            doi = None
            for article_id in article.findall(".//ArticleId"):
                if article_id.get("IdType") == "doi":
                    doi = article_id.text
                    break

            mesh_terms = [
                mesh.text
                for mesh in medline.findall(".//MeshHeading/DescriptorName")
                if mesh.text
            ]
            article_types = [pt.text for pt in article.findall(".//PublicationType")]

            return {
                "pmid": pmid,
                "title": title,
                "abstract": abstract,
                "authors": authors,
                "publication_date": date_str,
                "journal": journal,
                "doi": doi,
                "mesh_terms": mesh_terms,
                "article_types": article_types,
                "source": "pubmed_eutils",
                "scraped_at": datetime.now().isoformat(),
            }
        except Exception as exc:
            logger.error("Error parsing article XML: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Fallback methods
    # ------------------------------------------------------------------

    def _search_via_wayback(self, query: str, max_results: int) -> List[Dict[str, Any]]:  # noqa: ARG002
        """Fallback search using Archive.org Wayback Machine."""
        logger.warning("Wayback fallback not yet implemented")
        return []

    def _search_from_cache(self, query: str, max_results: int) -> List[Dict[str, Any]]:  # noqa: ARG002
        """Fallback search from local cache."""
        logger.warning("Cache fallback not yet implemented")
        return []

    # ------------------------------------------------------------------
    # Private API helper
    # ------------------------------------------------------------------

    def _search_via_eutils(
        self,
        query: str,
        max_results: int,
        start_date: Optional[str],
        end_date: Optional[str],
        research_type: Optional[str],
    ) -> List[Dict[str, Any]]:
        """Search PubMed using E-utilities API."""
        term = query
        if research_type:
            term += f" AND {research_type}[Publication Type]"

        params = self._build_eutils_params(
            {
                "db": "pubmed",
                "term": term,
                "retmax": max_results,
                "retmode": "json",
            }
        )
        if start_date:
            params["mindate"] = start_date
        if end_date:
            params["maxdate"] = end_date

        search_url = f"{self.EUTILS_BASE}esearch.fcgi"
        response = self.session.get(search_url, params=params, timeout=30)
        response.raise_for_status()

        search_results = response.json()
        pmids = search_results.get("esearchresult", {}).get("idlist", [])

        if not pmids:
            logger.info("No results found for query: %s", query)
            return []

        return self._fetch_article_details(pmids)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def search_medical_research(
        self,
        query: str,
        max_results: int = 100,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        research_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Search PubMed for medical research articles.

        Args:
            query: Search query (can include MeSH terms, keywords).
            max_results: Maximum number of results to return.
            start_date: Start date for publication filter (``YYYY/MM/DD``).
            end_date: End date for publication filter (``YYYY/MM/DD``).
            research_type: Type of research (e.g., ``"clinical_trial"``).

        Returns:
            List of article metadata dictionaries.

        Raises:
            ValueError: If query is empty.
            requests.RequestException: If API fails and fallback is disabled.
        """
        if not query:
            raise ValueError("Search query cannot be empty")

        try:
            return self._search_via_eutils(query, max_results, start_date, end_date, research_type)
        except Exception as exc:
            logger.error("E-utilities search failed: %s", exc)
            if self.use_fallback:
                try:
                    logger.info("Attempting fallback to wayback machine")
                    return self._search_via_wayback(query, max_results)
                except Exception as exc2:
                    logger.error("Wayback fallback failed: %s", exc2)
                    logger.info("Attempting to use local cache")
                    return self._search_from_cache(query, max_results)
            raise

    def scrape_biochemical_research(
        self,
        topic: str,
        max_results: int = 100,
        time_range_days: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Scrape biochemical research articles from PubMed.

        Args:
            topic: Biochemical research topic.
            max_results: Maximum number of results.
            time_range_days: Limit results to last N days.

        Returns:
            List of biochemical research articles.
        """
        query = f"{topic} AND (biochemistry[MeSH] OR molecular biology[MeSH])"
        start_date = None
        if time_range_days:
            start_date = (datetime.now() - timedelta(days=time_range_days)).strftime(
                "%Y/%m/%d"
            )
        return self.search_medical_research(
            query=query,
            max_results=max_results,
            start_date=start_date,
            research_type="research article",
        )

    def scrape_clinical_outcomes(
        self,
        condition: str,
        intervention: Optional[str] = None,
        max_results: int = 100,
    ) -> List[Dict[str, Any]]:
        """Scrape clinical outcome studies.

        Args:
            condition: Medical condition (e.g., ``"diabetes"``).
            intervention: Treatment or intervention.
            max_results: Maximum number of results.

        Returns:
            List of clinical outcome studies.
        """
        query = condition
        if intervention:
            query += f" AND {intervention}"
        query += " AND (clinical outcomes[MeSH] OR treatment outcome[MeSH])"

        return self.search_medical_research(
            query=query,
            max_results=max_results,
            research_type="clinical trial",
        )
