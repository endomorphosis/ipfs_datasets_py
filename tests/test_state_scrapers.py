"""
Unit tests for state law scrapers using mock HTML data.

These tests verify scraper logic without requiring network access.
"""

import pytest
import anyio
from unittest.mock import Mock, patch, AsyncMock
from bs4 import BeautifulSoup
import sys
from pathlib import Path

# Add parent directory to path to import from ipfs_datasets_py
sys.path.insert(0, str(Path(__file__).parent.parent))

from ipfs_datasets_py.mcp_server.tools.legal_dataset_tools.state_scrapers import (
    AlabamaScraper,
    ConnecticutScraper,
    DelawareScraper,
    GeorgiaScraper,
    IndianaScraper,
    MissouriScraper,
    WyomingScraper,
)


# Mock HTML samples for each state
MOCK_HTML_ALABAMA = """
<html>
<body>
    <h1>Alabama Code of 1975</h1>
    <div class="toc">
        <a href="/title13a.htm">Title 13A - Criminal Code</a>
        <a href="/title1.htm">Title 1 - General Provisions</a>
        <a href="/title10.htm">Title 10 - Corporations</a>
        <a href="/chapter6.htm">Chapter 6 - Homicide</a>
        <a href="/section13a-6-2.htm">Section 13A-6-2 - Murder</a>
        <!-- Navigation links that should be filtered -->
        <a href="/home.htm">Home</a>
        <a href="/about.htm">About</a>
        <a href="/search.htm">Search</a>
    </div>
</body>
</html>
"""

MOCK_HTML_CONNECTICUT = """
<html>
<body>
    <h1>Connecticut General Statutes</h1>
    <ul>
        <li><a href="/title1.htm">Title 1 - Provisions of General Application</a></li>
        <li><a href="/title53a.htm">Title 53a - Penal Code</a></li>
        <li><a href="/sec53a-54a.htm">Sec. 53a-54a - Murder</a></li>
        <li><a href="/chapter500.htm">Chapter 500 - Criminal Law</a></li>
        <!-- Navigation -->
        <a href="/">Home</a>
        <a href="/contact">Contact Us</a>
    </ul>
</body>
</html>
"""

MOCK_HTML_DELAWARE = """
<html>
<body>
    <h1>Delaware Code</h1>
    <div class="code-index">
        <a href="/title11/">Title 11 - Crimes and Criminal Procedure</a>
        <a href="/title11/chapter5/">Chapter 5 - Specific Offenses</a>
        <a href="/title11/chapter5/636.html">§ 636 - Murder First Degree</a>
        <a href="/title1/">Title 1 - General Provisions</a>
        <!-- Should be filtered -->
        <a href="/help">Help</a>
        <a href="/privacy">Privacy Policy</a>
    </div>
</body>
</html>
"""

MOCK_HTML_GEORGIA = """
<html>
<body>
    <h1>Official Code of Georgia</h1>
    <div class="statutes">
        <a href="/title16/">Title 16 - Crimes and Offenses</a>
        <a href="/title16/chapter5/">Chapter 5 - Crimes Against the Person</a>
        <a href="/title16/chapter5/section1.html">Section 16-5-1 - Murder</a>
        <a href="/title1/">Title 1 - General Provisions</a>
        <!-- Navigation -->
        <a href="/">Home</a>
    </div>
</body>
</html>
"""

MOCK_HTML_INDIANA = """
<html>
<body>
    <h1>Indiana Code</h1>
    <div class="ic-toc">
        <a href="/title35/">Title 35 - Criminal Law and Procedure</a>
        <a href="/title35/article42/">Article 42 - Offenses Against the Person</a>
        <a href="/title35/article42/chapter1/">Chapter 1 - Homicide</a>
        <a href="/ic35-42-1-1.html">IC 35-42-1-1 - Murder</a>
        <!-- Filter these -->
        <a href="/login">Login</a>
        <a href="/about">About</a>
    </div>
</body>
</html>
"""

MOCK_HTML_MISSOURI = """
<html>
<body>
    <h1>Missouri Revised Statutes</h1>
    <div class="rsmo">
        <a href="/chapter565.htm">Chapter 565 - Offenses Against the Person</a>
        <a href="/rsmo565.020.htm">RSMo 565.020 - First Degree Murder</a>
        <a href="/section565.021.htm">Section 565.021 - Second Degree Murder</a>
        <!-- Navigation -->
        <a href="/">Home</a>
        <a href="/search">Search</a>
    </div>
</body>
</html>
"""

MOCK_HTML_WYOMING = """
<html>
<body>
    <h1>Wyoming Statutes</h1>
    <div class="statutes">
        <a href="/title6.aspx">Title 6 - Crimes and Offenses</a>
        <a href="/title6/chapter2.aspx">Chapter 2 - Offenses Against the Person</a>
        <a href="/title6/chapter2/section101.aspx">§ 6-2-101 - First Degree Murder</a>
        <!-- Filter -->
        <a href="/default.aspx">Home</a>
    </div>
</body>
</html>
"""


class TestAlabamaScraper:
    """Tests for Alabama state law scraper."""
    
    @pytest.fixture
    def scraper(self):
        return AlabamaScraper("AL", "Alabama")
    
    def test_get_base_url(self, scraper):
        """Test that base URL is correctly set."""
        assert scraper.get_base_url() == "http://alisondb.legislature.state.al.us"
    
    def test_get_code_list(self, scraper):
        """Test that code list is returned."""
        codes = scraper.get_code_list()
        assert len(codes) == 1
        assert codes[0]['name'] == "Alabama Code"
        assert 'url' in codes[0]
    
    @pytest.mark.asyncio
    async def test_custom_scrape_with_mock_html(self, scraper):
        """Test scraping with mock HTML response."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.content = MOCK_HTML_ALABAMA.encode('utf-8')
        mock_response.raise_for_status = Mock()
        
        with patch('requests.get', return_value=mock_response):
            statutes = await scraper._custom_scrape_alabama(
                "Alabama Code",
                "http://test.url",
                "Ala. Code",
                max_sections=100
            )
        
        # Should find statute-related links, not navigation links
        assert len(statutes) > 0
        assert len(statutes) <= 5  # We have 5 valid statute links in mock
        
        # Verify no navigation links were captured
        for statute in statutes:
            link_text = statute.section_name.lower()
            assert 'home' not in link_text
            assert 'about' not in link_text
            assert 'search' not in link_text
    
    @pytest.mark.asyncio
    async def test_fallback_to_generic_on_error(self, scraper):
        """Test that scraper falls back to generic on error."""
        with patch('requests.get', side_effect=Exception("Network error")):
            # Mock the generic scraper to return empty list
            scraper._generic_scrape = AsyncMock(return_value=[])
            
            statutes = await scraper._custom_scrape_alabama(
                "Alabama Code",
                "http://test.url",
                "Ala. Code"
            )
            
            # Should have attempted fallback
            scraper._generic_scrape.assert_called_once()


class TestConnecticutScraper:
    """Tests for Connecticut state law scraper."""
    
    @pytest.fixture
    def scraper(self):
        return ConnecticutScraper("CT", "Connecticut")
    
    def test_get_base_url(self, scraper):
        assert scraper.get_base_url() == "https://www.cga.ct.gov"
    
    @pytest.mark.asyncio
    async def test_custom_scrape_accepts_numbered_links(self, scraper):
        """Test that scraper accepts links with numbers."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.content = MOCK_HTML_CONNECTICUT.encode('utf-8')
        mock_response.raise_for_status = Mock()
        
        with patch('requests.get', return_value=mock_response):
            statutes = await scraper._custom_scrape_connecticut(
                "Connecticut General Statutes",
                "http://test.url",
                "Conn. Gen. Stat."
            )
        
        assert len(statutes) > 0
        # Should accept titles with numbers
        section_names = [s.section_name for s in statutes]
        assert any('Title 1' in name or 'Title 53a' in name for name in section_names)


class TestDelawareScraper:
    """Tests for Delaware state law scraper."""
    
    @pytest.fixture
    def scraper(self):
        return DelawareScraper("DE", "Delaware")
    
    @pytest.mark.asyncio
    async def test_custom_scrape_with_symbols(self, scraper):
        """Test that scraper recognizes § symbol."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.content = MOCK_HTML_DELAWARE.encode('utf-8')
        mock_response.raise_for_status = Mock()
        
        with patch('requests.get', return_value=mock_response):
            statutes = await scraper._custom_scrape_delaware(
                "Delaware Code",
                "http://test.url",
                "Del. Code"
            )
        
        assert len(statutes) > 0
        # Should find the section with § symbol
        assert any('636' in s.section_name or '§' in s.section_name for s in statutes)


class TestGeorgiaScraper:
    """Tests for Georgia state law scraper."""
    
    @pytest.fixture
    def scraper(self):
        return GeorgiaScraper("GA", "Georgia")
    
    @pytest.mark.asyncio
    async def test_custom_scrape_filters_navigation(self, scraper):
        """Test that navigation links are filtered out."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.content = MOCK_HTML_GEORGIA.encode('utf-8')
        mock_response.raise_for_status = Mock()
        
        with patch('requests.get', return_value=mock_response):
            statutes = await scraper._custom_scrape_georgia(
                "Official Code of Georgia",
                "http://test.url",
                "Ga. Code Ann."
            )
        
        # Should not contain "Home" link
        for statute in statutes:
            assert 'Home' not in statute.section_name


class TestIndianaScraper:
    """Tests for Indiana state law scraper."""
    
    @pytest.fixture
    def scraper(self):
        return IndianaScraper("IN", "Indiana")
    
    @pytest.mark.asyncio
    async def test_recognizes_ic_abbreviation(self, scraper):
        """Test that scraper recognizes IC (Indiana Code) abbreviation."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.content = MOCK_HTML_INDIANA.encode('utf-8')
        mock_response.raise_for_status = Mock()
        
        with patch('requests.get', return_value=mock_response):
            statutes = await scraper._custom_scrape_indiana(
                "Indiana Code",
                "http://test.url",
                "Ind. Code"
            )
        
        assert len(statutes) > 0
        # Should find IC links
        assert any('IC' in s.section_name or 'Title 35' in s.section_name for s in statutes)


class TestMissouriScraper:
    """Tests for Missouri state law scraper."""
    
    @pytest.fixture
    def scraper(self):
        return MissouriScraper("MO", "Missouri")
    
    @pytest.mark.asyncio
    async def test_recognizes_rsmo_abbreviation(self, scraper):
        """Test that scraper recognizes RSMo abbreviation."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.content = MOCK_HTML_MISSOURI.encode('utf-8')
        mock_response.raise_for_status = Mock()
        
        with patch('requests.get', return_value=mock_response):
            statutes = await scraper._custom_scrape_missouri(
                "Missouri Revised Statutes",
                "http://test.url",
                "Mo. Rev. Stat."
            )
        
        assert len(statutes) > 0
        # Should find RSMo or Chapter links
        assert any('RSMo' in s.section_name or 'Chapter' in s.section_name for s in statutes)


class TestWyomingScraper:
    """Tests for Wyoming state law scraper."""
    
    @pytest.fixture
    def scraper(self):
        return WyomingScraper("WY", "Wyoming")
    
    @pytest.mark.asyncio
    async def test_custom_scrape_basic(self, scraper):
        """Test basic scraping functionality."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.content = MOCK_HTML_WYOMING.encode('utf-8')
        mock_response.raise_for_status = Mock()
        
        with patch('requests.get', return_value=mock_response):
            statutes = await scraper._custom_scrape_wyoming(
                "Wyoming Statutes",
                "http://test.url",
                "Wyo. Stat."
            )
        
        assert len(statutes) > 0
        # Should find title and chapter links
        assert any('Title' in s.section_name or 'Chapter' in s.section_name for s in statutes)


# Integration tests
class TestScraperIntegration:
    """Integration tests for all scrapers."""
    
    @pytest.mark.asyncio
    async def test_all_scrapers_have_base_url(self):
        """Verify all scrapers define base URL."""
        scrapers = [
            AlabamaScraper("AL", "Alabama"),
            ConnecticutScraper("CT", "Connecticut"),
            DelawareScraper("DE", "Delaware"),
            GeorgiaScraper("GA", "Georgia"),
            IndianaScraper("IN", "Indiana"),
            MissouriScraper("MO", "Missouri"),
            WyomingScraper("WY", "Wyoming"),
        ]
        
        for scraper in scrapers:
            base_url = scraper.get_base_url()
            assert base_url is not None
            assert len(base_url) > 0
            assert base_url.startswith('http')
    
    @pytest.mark.asyncio
    async def test_all_scrapers_have_code_list(self):
        """Verify all scrapers return code lists."""
        scrapers = [
            AlabamaScraper("AL", "Alabama"),
            ConnecticutScraper("CT", "Connecticut"),
            DelawareScraper("DE", "Delaware"),
            GeorgiaScraper("GA", "Georgia"),
            IndianaScraper("IN", "Indiana"),
            MissouriScraper("MO", "Missouri"),
            WyomingScraper("WY", "Wyoming"),
        ]
        
        for scraper in scrapers:
            codes = scraper.get_code_list()
            assert isinstance(codes, list)
            assert len(codes) > 0
            assert 'name' in codes[0]
            assert 'url' in codes[0]


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
