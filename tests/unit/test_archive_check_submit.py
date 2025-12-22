"""Test archive check and submit functionality."""
import pytest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock

from ipfs_datasets_py.mcp_server.tools.web_archive_tools.archive_check_submit import (
    check_and_submit_to_archives,
    batch_check_and_submit,
    _check_archive_org,
    _check_archive_is,
    _submit_to_archive_org,
    _submit_to_archive_is
)


class TestArchiveCheckSubmit:
    """Test archive check and submit functionality."""
    
    @pytest.mark.asyncio
    async def test_check_archive_org_present(self):
        """Test checking Archive.org when URL is present."""
        # GIVEN a URL that exists in Archive.org
        test_url = "https://www.example.com"
        
        with patch('ipfs_datasets_py.mcp_server.tools.web_archive_tools.archive_check_submit.search_wayback_machine') as mock_search:
            mock_search.return_value = {
                "status": "success",
                "count": 1,
                "results": [{
                    "wayback_url": "https://web.archive.org/web/20231215/https://www.example.com",
                    "timestamp": "20231215120000"
                }]
            }
            
            # WHEN checking Archive.org
            result = await _check_archive_org(test_url)
            
            # THEN it should be found
            assert result["present"] is True
            assert "wayback_url" in result["url"]
    
    @pytest.mark.asyncio
    async def test_check_archive_org_not_present(self):
        """Test checking Archive.org when URL is not present."""
        # GIVEN a URL that doesn't exist in Archive.org
        test_url = "https://www.newexample.com"
        
        with patch('ipfs_datasets_py.mcp_server.tools.web_archive_tools.archive_check_submit.search_wayback_machine') as mock_search:
            mock_search.return_value = {
                "status": "success",
                "count": 0,
                "results": []
            }
            
            # WHEN checking Archive.org
            result = await _check_archive_org(test_url)
            
            # THEN it should not be found
            assert result["present"] is False
    
    @pytest.mark.asyncio
    async def test_check_and_submit_both_present(self):
        """Test when URL is present in both archives."""
        # GIVEN a URL present in both archives
        test_url = "https://www.example.com"
        
        with patch('ipfs_datasets_py.mcp_server.tools.web_archive_tools.archive_check_submit._check_archive_org') as mock_check_org, \
             patch('ipfs_datasets_py.mcp_server.tools.web_archive_tools.archive_check_submit._check_archive_is') as mock_check_is:
            
            mock_check_org.return_value = {
                "present": True,
                "url": "https://web.archive.org/web/20231215/https://www.example.com"
            }
            mock_check_is.return_value = {
                "present": True,
                "url": "https://archive.is/abc123"
            }
            
            # WHEN checking and submitting
            result = await check_and_submit_to_archives(
                test_url,
                submit_if_missing=True
            )
            
            # THEN both should be present and nothing submitted
            assert result["status"] == "success"
            assert result["archive_org_present"] is True
            assert result["archive_is_present"] is True
            assert result["submitted_to_archive_org"] is False
            assert result["submitted_to_archive_is"] is False
    
    @pytest.mark.asyncio
    async def test_check_and_submit_missing_submit(self):
        """Test when URL is missing and should be submitted."""
        # GIVEN a URL not in any archives
        test_url = "https://www.newsite.com"
        
        with patch('ipfs_datasets_py.mcp_server.tools.web_archive_tools.archive_check_submit._check_archive_org') as mock_check_org, \
             patch('ipfs_datasets_py.mcp_server.tools.web_archive_tools.archive_check_submit._check_archive_is') as mock_check_is, \
             patch('ipfs_datasets_py.mcp_server.tools.web_archive_tools.archive_check_submit._submit_to_archive_org') as mock_submit_org, \
             patch('ipfs_datasets_py.mcp_server.tools.web_archive_tools.archive_check_submit._submit_to_archive_is') as mock_submit_is:
            
            mock_check_org.return_value = {"present": False}
            mock_check_is.return_value = {"present": False}
            mock_submit_org.return_value = {
                "status": "success",
                "archived_url": "https://web.archive.org/save/https://www.newsite.com"
            }
            mock_submit_is.return_value = {
                "status": "success",
                "archive_url": "https://archive.is/xyz789"
            }
            
            # WHEN checking and submitting
            result = await check_and_submit_to_archives(
                test_url,
                submit_if_missing=True
            )
            
            # THEN both should be submitted
            assert result["status"] == "success"
            assert result["archive_org_present"] is False
            assert result["archive_is_present"] is False
            assert result["submitted_to_archive_org"] is True
            assert result["submitted_to_archive_is"] is True
            assert result["archive_org_url"] is not None
            assert result["archive_is_url"] is not None
    
    @pytest.mark.asyncio
    async def test_check_and_submit_no_submission(self):
        """Test when URL is missing but submission is disabled."""
        # GIVEN a URL not in archives and submission disabled
        test_url = "https://www.newsite.com"
        
        with patch('ipfs_datasets_py.mcp_server.tools.web_archive_tools.archive_check_submit._check_archive_org') as mock_check_org, \
             patch('ipfs_datasets_py.mcp_server.tools.web_archive_tools.archive_check_submit._check_archive_is') as mock_check_is:
            
            mock_check_org.return_value = {"present": False}
            mock_check_is.return_value = {"present": False}
            
            # WHEN checking without submission
            result = await check_and_submit_to_archives(
                test_url,
                submit_if_missing=False
            )
            
            # THEN nothing should be submitted
            assert result["status"] == "success"
            assert result["archive_org_present"] is False
            assert result["archive_is_present"] is False
            assert result["submitted_to_archive_org"] is False
            assert result["submitted_to_archive_is"] is False
    
    @pytest.mark.asyncio
    async def test_batch_check_and_submit(self):
        """Test batch checking and submitting multiple URLs."""
        # GIVEN multiple URLs
        test_urls = [
            "https://www.example1.com",
            "https://www.example2.com",
            "https://www.example3.com"
        ]
        
        with patch('ipfs_datasets_py.mcp_server.tools.web_archive_tools.archive_check_submit.check_and_submit_to_archives') as mock_check:
            # Mock different results for each URL
            mock_check.side_effect = [
                {
                    "status": "success",
                    "archive_org_present": True,
                    "archive_is_present": True,
                    "submitted_to_archive_org": False,
                    "submitted_to_archive_is": False
                },
                {
                    "status": "success",
                    "archive_org_present": False,
                    "archive_is_present": False,
                    "submitted_to_archive_org": True,
                    "submitted_to_archive_is": True
                },
                {
                    "status": "error",
                    "error": "Network error"
                }
            ]
            
            # WHEN batch checking
            result = await batch_check_and_submit(
                urls=test_urls,
                submit_if_missing=True,
                max_concurrent=2
            )
            
            # THEN results should be aggregated
            assert result["status"] == "success"
            assert result["total_urls"] == 3
            assert result["already_archived_count"] == 1
            assert result["submitted_count"] == 1
            assert result["error_count"] == 1
    
    @pytest.mark.asyncio
    async def test_error_handling(self):
        """Test error handling in archive check."""
        # GIVEN a URL that causes an error
        test_url = "https://www.error.com"
        
        with patch('ipfs_datasets_py.mcp_server.tools.web_archive_tools.archive_check_submit._check_archive_org') as mock_check:
            mock_check.side_effect = Exception("Network error")
            
            # WHEN checking
            result = await check_and_submit_to_archives(test_url)
            
            # THEN should return error status
            assert result["status"] == "error"
            assert "error" in result
    
    @pytest.mark.asyncio
    async def test_selective_archive_checking(self):
        """Test checking only specific archives."""
        # GIVEN a URL
        test_url = "https://www.example.com"
        
        with patch('ipfs_datasets_py.mcp_server.tools.web_archive_tools.archive_check_submit._check_archive_org') as mock_check_org, \
             patch('ipfs_datasets_py.mcp_server.tools.web_archive_tools.archive_check_submit._check_archive_is') as mock_check_is:
            
            mock_check_org.return_value = {"present": True, "url": "org_url"}
            mock_check_is.return_value = {"present": True, "url": "is_url"}
            
            # WHEN checking only Archive.org
            result = await check_and_submit_to_archives(
                test_url,
                check_archive_org=True,
                check_archive_is=False
            )
            
            # THEN only Archive.org should be checked
            assert mock_check_org.called
            assert not mock_check_is.called
            assert result["archive_org_present"] is True
            assert result["archive_is_present"] is False


class TestUnifiedScraperIntegration:
    """Test integration with unified web scraper."""
    
    @pytest.mark.asyncio
    async def test_scraper_with_archive_check_enabled(self):
        """Test unified scraper with archive check enabled."""
        # GIVEN a scraper with archive check enabled
        from ipfs_datasets_py.unified_web_scraper import UnifiedWebScraper, ScraperConfig
        
        config = ScraperConfig(
            archive_check_before_scrape=True,
            archive_submit_if_missing=True
        )
        
        scraper = UnifiedWebScraper(config=config)
        
        with patch('ipfs_datasets_py.mcp_server.tools.web_archive_tools.archive_check_submit.check_and_submit_to_archives') as mock_check, \
             patch.object(scraper, '_scrape_with_fallback') as mock_scrape:
            
            mock_check.return_value = {
                "status": "success",
                "archive_org_present": False,
                "archive_is_present": False,
                "submitted_to_archive_org": True,
                "submitted_to_archive_is": True,
                "summary": "submitted to both archives"
            }
            
            mock_scrape.return_value = MagicMock(
                success=True,
                metadata={}
            )
            
            # WHEN scraping
            result = await scraper.scrape("https://www.example.com")
            
            # THEN archive check should be called
            assert mock_check.called
            assert "archive_check" in result.metadata
    
    @pytest.mark.asyncio
    async def test_scraper_with_archive_check_disabled(self):
        """Test unified scraper with archive check disabled."""
        # GIVEN a scraper with archive check disabled
        from ipfs_datasets_py.unified_web_scraper import UnifiedWebScraper, ScraperConfig
        
        config = ScraperConfig(
            archive_check_before_scrape=False
        )
        
        scraper = UnifiedWebScraper(config=config)
        
        with patch('ipfs_datasets_py.mcp_server.tools.web_archive_tools.archive_check_submit.check_and_submit_to_archives') as mock_check, \
             patch.object(scraper, '_scrape_with_fallback') as mock_scrape:
            
            mock_scrape.return_value = MagicMock(
                success=True,
                metadata={}
            )
            
            # WHEN scraping
            result = await scraper.scrape("https://www.example.com")
            
            # THEN archive check should not be called
            assert not mock_check.called
    
    @pytest.mark.asyncio
    async def test_scraper_continues_on_archive_error(self):
        """Test that scraper continues even if archive check fails."""
        # GIVEN a scraper with archive check that fails
        from ipfs_datasets_py.unified_web_scraper import UnifiedWebScraper, ScraperConfig
        
        config = ScraperConfig(
            archive_check_before_scrape=True
        )
        
        scraper = UnifiedWebScraper(config=config)
        
        with patch('ipfs_datasets_py.mcp_server.tools.web_archive_tools.archive_check_submit.check_and_submit_to_archives') as mock_check, \
             patch.object(scraper, '_scrape_with_fallback') as mock_scrape:
            
            mock_check.side_effect = Exception("Archive service unavailable")
            mock_scrape.return_value = MagicMock(
                success=True,
                metadata={}
            )
            
            # WHEN scraping
            result = await scraper.scrape("https://www.example.com")
            
            # THEN scraping should still succeed
            assert result.success is True
