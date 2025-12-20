#!/usr/bin/env python3
"""
Legal Scrapers - Core Module

Core scraper implementations with unified scraping support.
"""

from .base_scraper import BaseLegalScraper, run_async_scraper
from .municode import MunicodeScraper, scrape_municode
from .state_laws import StateLawsScraper, scrape_state_law
from .federal_register import FederalRegisterScraper, scrape_federal_register
from .us_code import USCodeScraper, scrape_us_code
from .ecode360 import ECode360Scraper, scrape_ecode360
from .municipal_code import MunicipalCodeScraper, scrape_municipal_code
from .recap import RECAPScraper, scrape_recap

__all__ = [
    # Base
    'BaseLegalScraper',
    'run_async_scraper',
    
    # Scrapers
    'MunicodeScraper',
    'StateLawsScraper',
    'FederalRegisterScraper',
    'USCodeScraper',
    'ECode360Scraper',
    'MunicipalCodeScraper',
    'RECAPScraper',
    
    # Convenience functions
    'scrape_municode',
    'scrape_state_law',
    'scrape_federal_register',
    'scrape_us_code',
    'scrape_ecode360',
    'scrape_municipal_code',
    'scrape_recap',
]
