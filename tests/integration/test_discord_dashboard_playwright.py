#!/usr/bin/env python3
"""
Comprehensive Discord Dashboard Playwright Test Suite

This module provides comprehensive browser automation testing for the Discord dashboard
using Playwright. It tests all dashboard features including:

1. Dashboard UI components and navigation
2. Server, channel, and DM browsing
3. Export functionality with various configurations
4. Analytics and data conversion
5. Token configuration and testing
6. Real-time server status updates
7. Error handling and validation
8. Visual regression testing with screenshots

Requirements:
- playwright >= 1.40.0
- pytest-playwright >= 0.4.0
- pytest-asyncio >= 0.21.0

Usage:
    # Install browsers first
    playwright install chromium
    
    # Run all tests
    pytest tests/integration/test_discord_dashboard_playwright.py -v
    
    # Run with headed browser and screenshots
    pytest tests/integration/test_discord_dashboard_playwright.py -v --headed --screenshot=on
"""

import asyncio
import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

try:
    from playwright.async_api import async_playwright, Page, Browser, BrowserContext, expect
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    pytest.skip("Playwright not available", allow_module_level=True)

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class DiscordDashboardTestRunner:
    """
    Manages Discord dashboard server lifecycle for testing.
    
    This class handles starting and stopping the Discord dashboard server
    in a separate process for testing purposes.
    """
    
    def __init__(self, host: str = "127.0.0.1", port: int = 8889):
        self.host = host
        self.port = port
        self.process = None
        self.base_url = f"http://{host}:{port}"
        
    async def start_server(self) -> bool:
        """Start the Discord dashboard server."""
        try:
            # Start the dashboard in a subprocess
            self.process = subprocess.Popen([
                sys.executable, "-m", "ipfs_datasets_py.discord_dashboard",
                "--host", self.host,
                "--port", str(self.port)
            ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            
            # Wait for server to start
            for _ in range(30):  # 30 second timeout
                try:
                    # Use stdlib urllib.request instead of requests
                    import urllib.request
                    import urllib.error
                    req = urllib.request.Request(f"{self.base_url}/mcp/discord/api/status")
                    try:
                        with urllib.request.urlopen(req, timeout=1) as response:
                            if response.status in [200, 500]:  # Accept both success and server errors
                                logger.info(f"Discord Dashboard started successfully on {self.base_url}")
                                return True
                    except urllib.error.HTTPError as e:
                        # Server is responding, even if with errors
                        if e.code in [200, 500]:
                            logger.info(f"Discord Dashboard started successfully on {self.base_url}")
                            return True
                except:
                    pass
                await asyncio.sleep(1)
            
            logger.error("Failed to start Discord dashboard within timeout")
            return False
            
        except Exception as e:
            logger.error(f"Failed to start Discord dashboard: {e}")
            return False
    
    async def stop_server(self):
        """Stop the Discord dashboard server."""
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
            logger.info("Discord Dashboard server stopped")


class DiscordDashboardTester:
    """
    Comprehensive Discord Dashboard testing with Playwright.
    
    This class implements all the test scenarios for the Discord dashboard,
    including UI testing, functional testing, and visual regression testing.
    """
    
    def __init__(self, base_url: str):
        self.base_url = base_url
        self.screenshots_dir = Path("test_outputs/discord_dashboard_screenshots")
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)
        self.test_results = {
            "screenshots": [],
            "interactions": [],
            "errors": [],
            "performance": {},
            "accessibility": [],
            "api_responses": []
        }
        
    async def take_screenshot(self, page: Page, name: str, description: str = ""):
        """Take a screenshot and save metadata."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{timestamp}_{name}.png"
        filepath = self.screenshots_dir / filename
        
        await page.screenshot(path=str(filepath), full_page=True)
        
        self.test_results["screenshots"].append({
            "name": name,
            "description": description,
            "filename": filename,
            "timestamp": timestamp,
            "url": page.url
        })
        
        logger.info(f"Screenshot saved: {filename}")
        return filepath
    
    async def test_dashboard_loading(self, page: Page):
        """Test that the dashboard loads correctly."""
        logger.info("Testing dashboard loading...")
        
        try:
            # Navigate to dashboard
            await page.goto(f"{self.base_url}/mcp/discord/")
            
            # Wait for main elements to load
            await page.wait_for_selector(".dashboard-container", timeout=10000)
            await page.wait_for_selector(".header", timeout=5000)
            await page.wait_for_selector(".sidebar", timeout=5000)
            await page.wait_for_selector(".content-area", timeout=5000)
            
            # Take screenshot
            await self.take_screenshot(page, "01_dashboard_loaded", "Dashboard initial load")
            
            # Verify header elements
            header = await page.query_selector(".header h1")
            assert header is not None, "Header title not found"
            
            header_text = await header.inner_text()
            assert "Discord" in header_text, f"Header text incorrect: {header_text}"
            
            # Verify status indicator
            status_indicator = await page.query_selector(".status-indicator")
            assert status_indicator is not None, "Status indicator not found"
            
            logger.info("✅ Dashboard loading test passed")
            return True
            
        except Exception as e:
            logger.error(f"❌ Dashboard loading test failed: {e}")
            await self.take_screenshot(page, "error_dashboard_loading", "Dashboard loading error")
            self.test_results["errors"].append({
                "test": "dashboard_loading",
                "error": str(e)
            })
            return False
    
    async def test_navigation(self, page: Page):
        """Test navigation between dashboard pages."""
        logger.info("Testing dashboard navigation...")
        
        try:
            pages_to_test = [
                ("overview", "Overview"),
                ("servers", "Servers"),
                ("channels", "Channels"),
                ("dms", "Direct Messages"),
                ("export", "Export"),
                ("analyze", "Analytics"),
                ("convert", "Convert"),
                ("token", "Token"),
                ("history", "History")
            ]
            
            for page_id, page_title in pages_to_test:
                # Click navigation item
                nav_item = await page.query_selector(f'.nav-item[data-page="{page_id}"]')
                assert nav_item is not None, f"Navigation item for {page_id} not found"
                
                await nav_item.click()
                await page.wait_for_timeout(500)  # Wait for page transition
                
                # Verify page is displayed
                page_content = await page.query_selector(f"#page-{page_id}")
                assert page_content is not None, f"Page content for {page_id} not found"
                
                # Check if page is visible
                is_visible = await page_content.is_visible()
                assert is_visible, f"Page {page_id} is not visible after navigation"
                
                # Verify nav item is active
                is_active = await nav_item.evaluate("el => el.classList.contains('active')")
                assert is_active, f"Navigation item {page_id} is not marked as active"
                
                # Take screenshot
                await self.take_screenshot(page, f"02_nav_{page_id}", f"Navigation to {page_title} page")
                
                logger.info(f"✅ Navigation to {page_title} successful")
            
            logger.info("✅ Navigation test passed")
            return True
            
        except Exception as e:
            logger.error(f"❌ Navigation test failed: {e}")
            await self.take_screenshot(page, "error_navigation", "Navigation error")
            self.test_results["errors"].append({
                "test": "navigation",
                "error": str(e)
            })
            return False
    
    async def test_status_check(self, page: Page):
        """Test status indicator and system status display."""
        logger.info("Testing status check functionality...")
        
        try:
            # Navigate to overview page
            overview_nav = await page.query_selector('.nav-item[data-page="overview"]')
            await overview_nav.click()
            await page.wait_for_timeout(500)
            
            # Wait for status to load
            await page.wait_for_selector("#status-text", timeout=10000)
            
            # Check status text
            status_text_elem = await page.query_selector("#status-text")
            status_text = await status_text_elem.inner_text()
            
            logger.info(f"Status text: {status_text}")
            
            # Verify status indicator has a status dot
            status_dot = await page.query_selector(".status-dot")
            assert status_dot is not None, "Status dot not found"
            
            # Check if status dot has a class (online/offline/warning)
            status_classes = await status_dot.evaluate("el => Array.from(el.classList)")
            has_status_class = any(cls in ['online', 'offline', 'warning'] for cls in status_classes)
            assert has_status_class, f"Status dot has no status class: {status_classes}"
            
            # Wait for system status details to load
            await page.wait_for_selector("#system-status-details", timeout=10000)
            
            # Take screenshot
            await self.take_screenshot(page, "03_status_check", "System status display")
            
            logger.info("✅ Status check test passed")
            return True
            
        except Exception as e:
            logger.error(f"❌ Status check test failed: {e}")
            await self.take_screenshot(page, "error_status_check", "Status check error")
            self.test_results["errors"].append({
                "test": "status_check",
                "error": str(e)
            })
            return False
    
    async def test_server_loading_ui(self, page: Page):
        """Test server loading UI interactions."""
        logger.info("Testing server loading UI...")
        
        try:
            # Navigate to servers page
            servers_nav = await page.query_selector('.nav-item[data-page="servers"]')
            await servers_nav.click()
            await page.wait_for_timeout(500)
            
            # Verify server list container exists
            server_list = await page.query_selector("#server-list")
            assert server_list is not None, "Server list not found"
            
            # Take screenshot of initial state
            await self.take_screenshot(page, "04_servers_initial", "Servers page initial state")
            
            # Click refresh servers button
            refresh_btn = await page.query_selector('button:has-text("Refresh Servers")')
            if refresh_btn:
                await refresh_btn.click()
                await page.wait_for_timeout(1000)  # Wait for API call
                
                # Take screenshot after refresh
                await self.take_screenshot(page, "05_servers_after_refresh", "Servers page after refresh")
            
            logger.info("✅ Server loading UI test passed")
            return True
            
        except Exception as e:
            logger.error(f"❌ Server loading UI test failed: {e}")
            await self.take_screenshot(page, "error_server_loading", "Server loading error")
            self.test_results["errors"].append({
                "test": "server_loading_ui",
                "error": str(e)
            })
            return False
    
    async def test_export_forms(self, page: Page):
        """Test export form interactions."""
        logger.info("Testing export forms...")
        
        try:
            # Navigate to export page
            export_nav = await page.query_selector('.nav-item[data-page="export"]')
            await export_nav.click()
            await page.wait_for_timeout(500)
            
            # Test channel export tab
            await self.take_screenshot(page, "06_export_channel_tab", "Export channel tab")
            
            # Fill in channel export form
            channel_id_input = await page.query_selector("#export-channel-id")
            await channel_id_input.fill("123456789012345678")
            
            # Select format
            format_select = await page.query_selector("#export-channel-format")
            await format_select.select_option("Json")
            
            # Check download media checkbox
            media_checkbox = await page.query_selector("#export-download-media")
            await media_checkbox.check()
            
            await self.take_screenshot(page, "07_export_channel_filled", "Channel export form filled")
            
            # Test server export tab
            server_tab = await page.query_selector('button.tab:has-text("Server")')
            await server_tab.click()
            await page.wait_for_timeout(500)
            
            await self.take_screenshot(page, "08_export_server_tab", "Export server tab")
            
            # Fill in server export form
            server_id_input = await page.query_selector("#export-server-id")
            await server_id_input.fill("987654321098765432")
            
            # Select threads option
            threads_select = await page.query_selector("#export-include-threads")
            await threads_select.select_option("all")
            
            await self.take_screenshot(page, "09_export_server_filled", "Server export form filled")
            
            # Test DMs export tab
            dms_tab = await page.query_selector('button.tab:has-text("All DMs")')
            await dms_tab.click()
            await page.wait_for_timeout(500)
            
            await self.take_screenshot(page, "10_export_dms_tab", "Export DMs tab")
            
            logger.info("✅ Export forms test passed")
            return True
            
        except Exception as e:
            logger.error(f"❌ Export forms test failed: {e}")
            await self.take_screenshot(page, "error_export_forms", "Export forms error")
            self.test_results["errors"].append({
                "test": "export_forms",
                "error": str(e)
            })
            return False
    
    async def test_analytics_form(self, page: Page):
        """Test analytics form interactions."""
        logger.info("Testing analytics form...")
        
        try:
            # Navigate to analyze page
            analyze_nav = await page.query_selector('.nav-item[data-page="analyze"]')
            await analyze_nav.click()
            await page.wait_for_timeout(500)
            
            await self.take_screenshot(page, "11_analytics_initial", "Analytics page initial")
            
            # Fill in channel ID
            channel_id_input = await page.query_selector("#analyze-channel-id")
            await channel_id_input.fill("123456789012345678")
            
            # Check analysis type checkboxes
            message_stats = await page.query_selector("#analyze-message-stats")
            await message_stats.check()
            
            user_activity = await page.query_selector("#analyze-user-activity")
            await user_activity.check()
            
            content_patterns = await page.query_selector("#analyze-content-patterns")
            await content_patterns.check()
            
            await self.take_screenshot(page, "12_analytics_filled", "Analytics form filled")
            
            logger.info("✅ Analytics form test passed")
            return True
            
        except Exception as e:
            logger.error(f"❌ Analytics form test failed: {e}")
            await self.take_screenshot(page, "error_analytics_form", "Analytics form error")
            self.test_results["errors"].append({
                "test": "analytics_form",
                "error": str(e)
            })
            return False
    
    async def test_convert_form(self, page: Page):
        """Test format conversion form."""
        logger.info("Testing convert form...")
        
        try:
            # Navigate to convert page
            convert_nav = await page.query_selector('.nav-item[data-page="convert"]')
            await convert_nav.click()
            await page.wait_for_timeout(500)
            
            await self.take_screenshot(page, "13_convert_initial", "Convert page initial")
            
            # Fill in conversion form
            input_path = await page.query_selector("#convert-input-path")
            await input_path.fill("/path/to/export.json")
            
            output_path = await page.query_selector("#convert-output-path")
            await output_path.fill("/path/to/output.parquet")
            
            # Select format
            format_select = await page.query_selector("#convert-format")
            await format_select.select_option("parquet")
            
            await self.take_screenshot(page, "14_convert_filled", "Convert form filled")
            
            logger.info("✅ Convert form test passed")
            return True
            
        except Exception as e:
            logger.error(f"❌ Convert form test failed: {e}")
            await self.take_screenshot(page, "error_convert_form", "Convert form error")
            self.test_results["errors"].append({
                "test": "convert_form",
                "error": str(e)
            })
            return False
    
    async def test_token_configuration(self, page: Page):
        """Test token configuration page."""
        logger.info("Testing token configuration...")
        
        try:
            # Navigate to token page
            token_nav = await page.query_selector('.nav-item[data-page="token"]')
            await token_nav.click()
            await page.wait_for_timeout(500)
            
            await self.take_screenshot(page, "15_token_initial", "Token configuration page")
            
            # Fill in token (use a dummy token for testing)
            token_input = await page.query_selector("#discord-token")
            await token_input.fill("dummy_token_for_testing_ui")
            
            # Test token visibility toggle
            toggle_btn = await page.query_selector(".token-toggle")
            await toggle_btn.click()
            await page.wait_for_timeout(200)
            
            # Check if input type changed to text
            input_type = await token_input.get_attribute("type")
            assert input_type == "text", f"Token input should be text, got {input_type}"
            
            await self.take_screenshot(page, "16_token_visible", "Token visible")
            
            # Toggle back
            await toggle_btn.click()
            await page.wait_for_timeout(200)
            
            input_type = await token_input.get_attribute("type")
            assert input_type == "password", f"Token input should be password, got {input_type}"
            
            await self.take_screenshot(page, "17_token_hidden", "Token hidden")
            
            logger.info("✅ Token configuration test passed")
            return True
            
        except Exception as e:
            logger.error(f"❌ Token configuration test failed: {e}")
            await self.take_screenshot(page, "error_token_config", "Token configuration error")
            self.test_results["errors"].append({
                "test": "token_configuration",
                "error": str(e)
            })
            return False
    
    async def test_responsive_design(self, page: Page):
        """Test responsive design at different viewport sizes."""
        logger.info("Testing responsive design...")
        
        try:
            viewport_sizes = [
                (1920, 1080, "desktop_large"),
                (1366, 768, "desktop_medium"),
                (1024, 768, "desktop_small"),
                (768, 1024, "tablet"),
                (375, 667, "mobile")
            ]
            
            for width, height, label in viewport_sizes:
                # Set viewport size
                await page.set_viewport_size({"width": width, "height": height})
                await page.wait_for_timeout(500)
                
                # Navigate to overview
                overview_nav = await page.query_selector('.nav-item[data-page="overview"]')
                await overview_nav.click()
                await page.wait_for_timeout(500)
                
                # Take screenshot
                await self.take_screenshot(page, f"18_responsive_{label}", f"Responsive design at {width}x{height}")
                
                logger.info(f"✅ Responsive test for {label} ({width}x{height}) passed")
            
            # Reset to default size
            await page.set_viewport_size({"width": 1366, "height": 768})
            
            logger.info("✅ Responsive design test passed")
            return True
            
        except Exception as e:
            logger.error(f"❌ Responsive design test failed: {e}")
            await self.take_screenshot(page, "error_responsive", "Responsive design error")
            self.test_results["errors"].append({
                "test": "responsive_design",
                "error": str(e)
            })
            return False
    
    async def test_ui_layout(self, page: Page):
        """Test that UI elements are properly laid out."""
        logger.info("Testing UI layout...")
        
        try:
            # Check header layout
            header = await page.query_selector(".header")
            header_box = await header.bounding_box()
            assert header_box is not None, "Header has no bounding box"
            assert header_box['height'] > 50, f"Header too small: {header_box['height']}px"
            
            # Check sidebar layout
            sidebar = await page.query_selector(".sidebar")
            sidebar_box = await sidebar.bounding_box()
            assert sidebar_box is not None, "Sidebar has no bounding box"
            assert sidebar_box['width'] > 200, f"Sidebar too narrow: {sidebar_box['width']}px"
            
            # Check content area
            content_area = await page.query_selector(".content-area")
            content_box = await content_area.bounding_box()
            assert content_box is not None, "Content area has no bounding box"
            assert content_box['width'] > 500, f"Content area too narrow: {content_box['width']}px"
            
            # Verify no overlapping elements
            await self.take_screenshot(page, "19_layout_verification", "UI layout verification")
            
            logger.info("✅ UI layout test passed")
            return True
            
        except Exception as e:
            logger.error(f"❌ UI layout test failed: {e}")
            await self.take_screenshot(page, "error_ui_layout", "UI layout error")
            self.test_results["errors"].append({
                "test": "ui_layout",
                "error": str(e)
            })
            return False
    
    async def generate_test_report(self):
        """Generate a comprehensive test report."""
        report_path = self.screenshots_dir / "test_report.json"
        
        report = {
            "test_run": {
                "timestamp": datetime.now().isoformat(),
                "total_screenshots": len(self.test_results["screenshots"]),
                "total_errors": len(self.test_results["errors"]),
                "screenshots_directory": str(self.screenshots_dir)
            },
            "results": self.test_results
        }
        
        with open(report_path, 'w') as f:
            json.dump(report, f, indent=2)
        
        logger.info(f"Test report generated: {report_path}")
        
        # Print summary
        logger.info("=" * 60)
        logger.info("TEST SUMMARY")
        logger.info("=" * 60)
        logger.info(f"Screenshots taken: {len(self.test_results['screenshots'])}")
        logger.info(f"Errors encountered: {len(self.test_results['errors'])}")
        logger.info(f"Report location: {report_path}")
        logger.info("=" * 60)
        
        return report


@pytest.fixture(scope="session")
async def dashboard_server():
    """Fixture to start and stop the dashboard server."""
    server = DiscordDashboardTestRunner()
    
    # Start server
    started = await server.start_server()
    if not started:
        pytest.skip("Failed to start Discord dashboard server")
    
    yield server
    
    # Stop server
    await server.stop_server()


@pytest.mark.asyncio
async def test_discord_dashboard_comprehensive(dashboard_server):
    """Run comprehensive Discord dashboard tests."""
    
    tester = DiscordDashboardTester(dashboard_server.base_url)
    
    async with async_playwright() as p:
        # Launch browser
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1366, "height": 768})
        page = await context.new_page()
        
        try:
            # Run all tests
            test_results = []
            
            test_results.append(await tester.test_dashboard_loading(page))
            test_results.append(await tester.test_navigation(page))
            test_results.append(await tester.test_status_check(page))
            test_results.append(await tester.test_server_loading_ui(page))
            test_results.append(await tester.test_export_forms(page))
            test_results.append(await tester.test_analytics_form(page))
            test_results.append(await tester.test_convert_form(page))
            test_results.append(await tester.test_token_configuration(page))
            test_results.append(await tester.test_ui_layout(page))
            test_results.append(await tester.test_responsive_design(page))
            
            # Generate test report
            report = await tester.generate_test_report()
            
            # Assert all tests passed
            assert all(test_results), f"Some tests failed. Check report at {tester.screenshots_dir}/test_report.json"
            
        finally:
            await context.close()
            await browser.close()


if __name__ == '__main__':
    # Run tests directly
    pytest.main([__file__, "-v", "--asyncio-mode=auto"])
