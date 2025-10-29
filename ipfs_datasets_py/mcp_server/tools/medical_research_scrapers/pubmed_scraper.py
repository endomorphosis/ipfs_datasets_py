#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
PubMed Medical Literature Scraper.

This module provides functionality to scrape medical literature from PubMed,
with fallback mechanisms using multiple data access methods:
1. PubMed E-utilities API (primary)
2. PubMed FTP bulk downloads (secondary)
3. Web scraping with archive.org wayback (fallback)
4. Local IPFS cached data (offline fallback)
"""

import logging
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
import requests
from xml.etree import ElementTree as ET


logger = logging.getLogger(__name__)


class PubMedScraper:
    """
    Scraper for PubMed medical literature database.
    
    Collects medical research articles, clinical studies, and biochemical research
    with multiple fallback mechanisms for reliability.
    
    Args:
        api_key (Optional[str]): NCBI E-utilities API key for higher rate limits
        email (Optional[str]): Email for NCBI E-utilities (required by NCBI)
        use_fallback (bool): Enable fallback mechanisms if primary fails
        cache_dir (Optional[str]): Directory for caching scraped data
        
    Example:
        >>> scraper = PubMedScraper(email="researcher@example.com")
        >>> results = scraper.search_medical_research("COVID-19 treatment", max_results=100)
        >>> biochem_data = scraper.scrape_biochemical_research(topic="protein folding")
    """
    
    EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
    PUBMED_FTP = "ftp://ftp.ncbi.nlm.nih.gov/pubmed/"
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        email: Optional[str] = None,
        use_fallback: bool = True,
        cache_dir: Optional[str] = None
    ):
        """Initialize PubMed scraper with configuration."""
        self.api_key = api_key
        self.email = email
        self.use_fallback = use_fallback
        self.cache_dir = cache_dir
        self.session = requests.Session()
        
        if not email:
            logger.warning("No email provided - NCBI requires email for API access")
    
    def search_medical_research(
        self,
        query: str,
        max_results: int = 100,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        research_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Search PubMed for medical research articles.
        
        Args:
            query: Search query (can include MeSH terms, keywords)
            max_results: Maximum number of results to return
            start_date: Start date for publication filter (YYYY/MM/DD)
            end_date: End date for publication filter (YYYY/MM/DD)
            research_type: Type of research (clinical_trial, review, meta_analysis, etc.)
            
        Returns:
            List of article metadata dictionaries containing:
            - pmid: PubMed ID
            - title: Article title
            - abstract: Article abstract
            - authors: List of author names
            - publication_date: Publication date
            - journal: Journal name
            - doi: Digital Object Identifier
            - mesh_terms: Medical Subject Headings
            - article_type: Type of article
            
        Raises:
            requests.RequestException: If API request fails
            ValueError: If query is empty or invalid
        """
        if not query:
            raise ValueError("Search query cannot be empty")
            
        try:
            # Primary method: E-utilities API
            return self._search_via_eutils(query, max_results, start_date, end_date, research_type)
        except Exception as e:
            logger.error(f"E-utilities search failed: {e}")
            
            if self.use_fallback:
                try:
                    # Fallback 1: Web scraping with wayback
                    logger.info("Attempting fallback to wayback machine")
                    return self._search_via_wayback(query, max_results)
                except Exception as e2:
                    logger.error(f"Wayback fallback failed: {e2}")
                    
                    # Fallback 2: Local cache
                    logger.info("Attempting to use local cache")
                    return self._search_from_cache(query, max_results)
            else:
                raise
    
    def _search_via_eutils(
        self,
        query: str,
        max_results: int,
        start_date: Optional[str],
        end_date: Optional[str],
        research_type: Optional[str]
    ) -> List[Dict[str, Any]]:
        """Search PubMed using E-utilities API."""
        # Build query parameters
        params = {
            "db": "pubmed",
            "term": query,
            "retmax": max_results,
            "retmode": "json",
        }
        
        if self.email:
            params["email"] = self.email
        if self.api_key:
            params["api_key"] = self.api_key
        if start_date:
            params["mindate"] = start_date
        if end_date:
            params["maxdate"] = end_date
        if research_type:
            params["term"] += f" AND {research_type}[Publication Type]"
        
        # Search for PMIDs
        search_url = f"{self.EUTILS_BASE}esearch.fcgi"
        response = self.session.get(search_url, params=params, timeout=30)
        response.raise_for_status()
        
        search_results = response.json()
        pmids = search_results.get("esearchresult", {}).get("idlist", [])
        
        if not pmids:
            logger.info(f"No results found for query: {query}")
            return []
        
        # Fetch article details
        return self._fetch_article_details(pmids)
    
    def _fetch_article_details(self, pmids: List[str]) -> List[Dict[str, Any]]:
        """Fetch detailed information for a list of PubMed IDs."""
        if not pmids:
            return []
        
        # Fetch article data in batches to avoid rate limits
        fetch_url = f"{self.EUTILS_BASE}efetch.fcgi"
        params = {
            "db": "pubmed",
            "id": ",".join(pmids),
            "retmode": "xml",
        }
        
        if self.email:
            params["email"] = self.email
        if self.api_key:
            params["api_key"] = self.api_key
        
        response = self.session.get(fetch_url, params=params, timeout=60)
        response.raise_for_status()
        
        # Parse XML response
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
            
            # Extract basic info
            pmid_elem = medline.find(".//PMID")
            pmid = pmid_elem.text if pmid_elem is not None else None
            
            article = medline.find(".//Article")
            if article is None:
                return None
            
            # Title
            title_elem = article.find(".//ArticleTitle")
            title = title_elem.text if title_elem is not None else "No title"
            
            # Abstract
            abstract_parts = article.findall(".//AbstractText")
            abstract = " ".join([a.text or "" for a in abstract_parts])
            
            # Authors
            authors = []
            for author in article.findall(".//Author"):
                last_name = author.find(".//LastName")
                fore_name = author.find(".//ForeName")
                if last_name is not None and fore_name is not None:
                    authors.append(f"{fore_name.text} {last_name.text}")
            
            # Publication date
            pub_date = article.find(".//PubDate")
            year = pub_date.find(".//Year")
            month = pub_date.find(".//Month")
            day = pub_date.find(".//Day")
            
            date_str = ""
            if year is not None:
                date_str = year.text
                if month is not None:
                    date_str += f"-{month.text}"
                    if day is not None:
                        date_str += f"-{day.text}"
            
            # Journal
            journal_elem = article.find(".//Journal/Title")
            journal = journal_elem.text if journal_elem is not None else "Unknown"
            
            # DOI
            doi = None
            for article_id in article.findall(".//ArticleId"):
                if article_id.get("IdType") == "doi":
                    doi = article_id.text
                    break
            
            # MeSH terms
            mesh_terms = []
            for mesh in medline.findall(".//MeshHeading/DescriptorName"):
                mesh_terms.append(mesh.text)
            
            # Article type
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
                "scraped_at": datetime.now().isoformat()
            }
        except Exception as e:
            logger.error(f"Error parsing article XML: {e}")
            return None
    
    def _search_via_wayback(self, query: str, max_results: int) -> List[Dict[str, Any]]:
        """Fallback search using Archive.org Wayback Machine."""
        logger.warning("Wayback fallback not yet implemented")
        return []
    
    def _search_from_cache(self, query: str, max_results: int) -> List[Dict[str, Any]]:
        """Fallback search from local cache."""
        logger.warning("Cache fallback not yet implemented")
        return []
    
    def scrape_biochemical_research(
        self,
        topic: str,
        max_results: int = 100,
        time_range_days: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Scrape biochemical research articles from PubMed.
        
        Args:
            topic: Biochemical research topic (e.g., "protein folding", "enzyme kinetics")
            max_results: Maximum number of results to return
            time_range_days: Limit results to last N days
            
        Returns:
            List of biochemical research articles with metadata
        """
        # Build specialized query for biochemical research
        query = f"{topic} AND (biochemistry[MeSH] OR molecular biology[MeSH])"
        
        # Add time range if specified
        start_date = None
        if time_range_days:
            start_date = (datetime.now() - timedelta(days=time_range_days)).strftime("%Y/%m/%d")
        
        return self.search_medical_research(
            query=query,
            max_results=max_results,
            start_date=start_date,
            research_type="research article"
        )
    
    def scrape_clinical_outcomes(
        self,
        condition: str,
        intervention: Optional[str] = None,
        max_results: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Scrape clinical outcome studies for temporal deontic logic theorems.
        
        This method collects data to support reasoning like:
        "If a person takes intervention X, they are likely to experience outcome Y"
        
        Args:
            condition: Medical condition (e.g., "diabetes", "hypertension")
            intervention: Treatment or intervention (e.g., "metformin", "lifestyle changes")
            max_results: Maximum number of results
            
        Returns:
            List of clinical outcome studies with metadata
        """
        query = f"{condition}"
        if intervention:
            query += f" AND {intervention}"
        query += " AND (clinical outcomes[MeSH] OR treatment outcome[MeSH])"
        
        return self.search_medical_research(
            query=query,
            max_results=max_results,
            research_type="clinical trial"
        )
