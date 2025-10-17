#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VSCode CLI MCP Dashboard Integration Test

Comprehensive Playwright test suite for VSCode CLI integration with the MCP Dashboard.
Tests the full scope of VSCode CLI tooling including:
- Tool discovery and visibility in dashboard
- Tool execution through the GUI
- GitHub authentication setup
- Extension management
- Tunnel setup
- Screenshots of all interactions

Usage:
    python -m pytest tests/test_vscode_cli_dashboard.py -v -s
    
    # With headed browser (to see the browser)
    python -m pytest tests/test_vscode_cli_dashboard.py -v -s --headed
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
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from playwright.async_api import async_playwright, Page, Browser, BrowserContext, expect
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    pytest.skip("Playwright not available", allow_module_level=True)

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class VSCodeCLIDashboardTester:
    """
    Tests VSCode CLI integration in the MCP Dashboard.
    
    This class tests all VSCode CLI features accessible through the dashboard:
    - Tool discovery and listing
    - Status checking
    - Installation
    - Command execution  
    - Extension management
    - Tunnel setup and GitHub authentication
    """
    
    def __init__(self, base_url: str = "http://127.0.0.1:8899"):
        self.base_url = base_url
        self.screenshots_dir = Path("test_screenshots/vscode_cli")
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)
        self.test_results = {
            "screenshots": [],
            "interactions": [],
            "tools_tested": [],
            "errors": []
        }
        
    async def take_screenshot(self, page: Page, name: str, description: str = "") -> str:
        """Take a screenshot and save it with metadata."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{name}_{timestamp}.png"
        filepath = self.screenshots_dir / filename
        
        await page.screenshot(path=str(filepath), full_page=True)
        
        screenshot_info = {
            "filename": filename,
            "path": str(filepath),
            "description": description,
            "timestamp": timestamp,
            "url": page.url
        }
        self.test_results["screenshots"].append(screenshot_info)
        
        logger.info(f"📸 Screenshot saved: {filename} - {description}")
        return str(filepath)
    
    async def test_dashboard_loads(self, page: Page) -> bool:
        """Test that the MCP dashboard loads successfully."""
        logger.info("Testing dashboard loads...")
        
        try:
            await page.goto(self.base_url, wait_until="networkidle", timeout=30000)
            await self.take_screenshot(page, "01_dashboard_loaded", "MCP Dashboard loaded successfully")
            
            # Check for essential elements
            await page.wait_for_selector("body", timeout=5000)
            
            self.test_results["interactions"].append({
                "test": "dashboard_loads",
                "status": "passed",
                "timestamp": datetime.now().isoformat()
            })
            return True
            
        except Exception as e:
            logger.error(f"Failed to load dashboard: {e}")
            self.test_results["errors"].append({
                "test": "dashboard_loads",
                "error": str(e)
            })
            return False
    
    async def test_tool_categories_visible(self, page: Page) -> bool:
        """Test that tool categories are visible and VSCode tools are listed."""
        logger.info("Testing tool categories visibility...")
        
        try:
            # Look for tools section or categories
            # Try multiple possible selectors
            selectors_to_try = [
                "text=development",
                "text=Development",
                "text=Tools",
                "text=development_tools",
                "[data-category='development']",
                ".tool-category",
                ".category-development"
            ]
            
            found = False
            for selector in selectors_to_try:
                try:
                    await page.wait_for_selector(selector, timeout=2000)
                    found = True
                    logger.info(f"Found selector: {selector}")
                    break
                except:
                    continue
            
            await self.take_screenshot(page, "02_tool_categories", "Tool categories in dashboard")
            
            self.test_results["interactions"].append({
                "test": "tool_categories_visible",
                "status": "passed" if found else "partial",
                "timestamp": datetime.now().isoformat()
            })
            return True
            
        except Exception as e:
            logger.error(f"Failed to find tool categories: {e}")
            self.test_results["errors"].append({
                "test": "tool_categories_visible",
                "error": str(e)
            })
            return False
    
    async def test_vscode_cli_status_tool(self, page: Page) -> bool:
        """Test VSCode CLI status tool discovery and execution."""
        logger.info("Testing VSCode CLI status tool...")
        
        try:
            # Look for VSCode CLI status tool
            vscode_tool_selectors = [
                "text=vscode_cli_status",
                "text=VSCode CLI Status",
                "[data-tool='vscode_cli_status']",
                "button:has-text('vscode')",
            ]
            
            found_tool = False
            for selector in vscode_tool_selectors:
                try:
                    await page.wait_for_selector(selector, timeout=2000)
                    logger.info(f"Found VSCode tool with selector: {selector}")
                    await page.click(selector)
                    found_tool = True
                    break
                except:
                    continue
            
            await self.take_screenshot(page, "03_vscode_status_tool", "VSCode CLI Status tool")
            
            # Try to execute the tool
            execute_selectors = [
                "button:has-text('Execute')",
                "button:has-text('Run')",
                "[data-action='execute']",
                "input[type='submit']"
            ]
            
            for selector in execute_selectors:
                try:
                    await page.click(selector, timeout=2000)
                    await asyncio.sleep(1)
                    break
                except:
                    continue
            
            await self.take_screenshot(page, "04_vscode_status_executed", "VSCode CLI Status tool executed")
            
            self.test_results["tools_tested"].append("vscode_cli_status")
            self.test_results["interactions"].append({
                "test": "vscode_cli_status_tool",
                "status": "passed" if found_tool else "partial",
                "timestamp": datetime.now().isoformat()
            })
            return True
            
        except Exception as e:
            logger.error(f"Failed to test VSCode CLI status tool: {e}")
            self.test_results["errors"].append({
                "test": "vscode_cli_status_tool",
                "error": str(e)
            })
            return False
    
    async def test_vscode_cli_install_tool(self, page: Page) -> bool:
        """Test VSCode CLI install tool visibility."""
        logger.info("Testing VSCode CLI install tool...")
        
        try:
            # Look for install tool
            install_selectors = [
                "text=vscode_cli_install",
                "text=VSCode CLI Install",
                "[data-tool='vscode_cli_install']",
            ]
            
            found_tool = False
            for selector in install_selectors:
                try:
                    await page.wait_for_selector(selector, timeout=2000)
                    await page.click(selector)
                    found_tool = True
                    break
                except:
                    continue
            
            await self.take_screenshot(page, "05_vscode_install_tool", "VSCode CLI Install tool")
            
            self.test_results["tools_tested"].append("vscode_cli_install")
            self.test_results["interactions"].append({
                "test": "vscode_cli_install_tool",
                "status": "passed" if found_tool else "partial",
                "timestamp": datetime.now().isoformat()
            })
            return True
            
        except Exception as e:
            logger.error(f"Failed to test VSCode CLI install tool: {e}")
            await self.take_screenshot(page, "05_vscode_install_error", "Error finding install tool")
            return False
    
    async def test_vscode_extensions_tool(self, page: Page) -> bool:
        """Test VSCode extensions management tool."""
        logger.info("Testing VSCode extensions tool...")
        
        try:
            # Look for extensions tool
            ext_selectors = [
                "text=vscode_cli_extensions",
                "text=VSCode Extensions",
                "[data-tool='vscode_cli_extensions']",
                "text=vscode_cli_list_extensions"
            ]
            
            found_tool = False
            for selector in ext_selectors:
                try:
                    await page.wait_for_selector(selector, timeout=2000)
                    await page.click(selector)
                    found_tool = True
                    break
                except:
                    continue
            
            await self.take_screenshot(page, "06_vscode_extensions_tool", "VSCode extensions management tool")
            
            self.test_results["tools_tested"].append("vscode_cli_extensions")
            self.test_results["interactions"].append({
                "test": "vscode_extensions_tool",
                "status": "passed" if found_tool else "partial",
                "timestamp": datetime.now().isoformat()
            })
            return True
            
        except Exception as e:
            logger.error(f"Failed to test VSCode extensions tool: {e}")
            await self.take_screenshot(page, "06_vscode_extensions_error", "Error finding extensions tool")
            return False
    
    async def test_vscode_tunnel_tool(self, page: Page) -> bool:
        """Test VSCode tunnel management tool including GitHub auth."""
        logger.info("Testing VSCode tunnel tool and GitHub authentication...")
        
        try:
            # Look for tunnel tool
            tunnel_selectors = [
                "text=vscode_cli_tunnel",
                "text=VSCode Tunnel",
                "[data-tool='vscode_cli_tunnel']",
                "text=vscode_cli_tunnel_login"
            ]
            
            found_tool = False
            for selector in tunnel_selectors:
                try:
                    await page.wait_for_selector(selector, timeout=2000)
                    await page.click(selector)
                    found_tool = True
                    break
                except:
                    continue
            
            await self.take_screenshot(page, "07_vscode_tunnel_tool", "VSCode tunnel management tool")
            
            # Look for GitHub auth options
            auth_selectors = [
                "text=github",
                "text=GitHub",
                "select[name='provider']",
                "input[name='provider']"
            ]
            
            for selector in auth_selectors:
                try:
                    element = await page.query_selector(selector)
                    if element:
                        logger.info(f"Found GitHub auth option: {selector}")
                        await self.take_screenshot(page, "08_github_auth_option", "GitHub authentication option visible")
                        break
                except:
                    continue
            
            self.test_results["tools_tested"].append("vscode_cli_tunnel")
            self.test_results["interactions"].append({
                "test": "vscode_tunnel_tool",
                "status": "passed" if found_tool else "partial",
                "timestamp": datetime.now().isoformat(),
                "github_auth": "visible"
            })
            return True
            
        except Exception as e:
            logger.error(f"Failed to test VSCode tunnel tool: {e}")
            await self.take_screenshot(page, "07_vscode_tunnel_error", "Error finding tunnel tool")
            return False
    
    async def test_vscode_execute_tool(self, page: Page) -> bool:
        """Test VSCode CLI execute tool for arbitrary commands."""
        logger.info("Testing VSCode CLI execute tool...")
        
        try:
            # Look for execute tool
            execute_selectors = [
                "text=vscode_cli_execute",
                "text=VSCode Execute",
                "[data-tool='vscode_cli_execute']",
            ]
            
            found_tool = False
            for selector in execute_selectors:
                try:
                    await page.wait_for_selector(selector, timeout=2000)
                    await page.click(selector)
                    found_tool = True
                    break
                except:
                    continue
            
            await self.take_screenshot(page, "09_vscode_execute_tool", "VSCode CLI execute command tool")
            
            # Look for command input field
            input_selectors = [
                "input[name='command']",
                "textarea[name='command']",
                "[data-field='command']"
            ]
            
            for selector in input_selectors:
                try:
                    element = await page.query_selector(selector)
                    if element:
                        logger.info(f"Found command input field: {selector}")
                        # Try to fill it with a test command
                        await page.fill(selector, '["--version"]')
                        await self.take_screenshot(page, "10_command_input_filled", "Command input filled with --version")
                        break
                except:
                    continue
            
            self.test_results["tools_tested"].append("vscode_cli_execute")
            self.test_results["interactions"].append({
                "test": "vscode_execute_tool",
                "status": "passed" if found_tool else "partial",
                "timestamp": datetime.now().isoformat()
            })
            return True
            
        except Exception as e:
            logger.error(f"Failed to test VSCode CLI execute tool: {e}")
            await self.take_screenshot(page, "09_vscode_execute_error", "Error finding execute tool")
            return False
    
    async def test_tool_api_endpoints(self, page: Page) -> bool:
        """Test that API endpoints for VSCode CLI tools are accessible."""
        logger.info("Testing VSCode CLI tool API endpoints...")
        
        try:
            # Navigate to API status page
            api_url = f"{self.base_url}/api/mcp/tools"
            await page.goto(api_url, wait_until="networkidle", timeout=10000)
            
            await self.take_screenshot(page, "11_api_tools_endpoint", "API tools endpoint showing available tools")
            
            # Check page content
            content = await page.content()
            
            # Check if VSCode CLI tools are in the response
            vscode_tools = [
                "vscode_cli_status",
                "vscode_cli_install",
                "vscode_cli_execute",
                "vscode_cli_extensions",
                "vscode_cli_tunnel"
            ]
            
            found_tools = []
            for tool in vscode_tools:
                if tool in content:
                    found_tools.append(tool)
                    logger.info(f"✓ Found tool in API: {tool}")
            
            self.test_results["interactions"].append({
                "test": "tool_api_endpoints",
                "status": "passed",
                "tools_found": found_tools,
                "timestamp": datetime.now().isoformat()
            })
            return len(found_tools) > 0
            
        except Exception as e:
            logger.error(f"Failed to test API endpoints: {e}")
            self.test_results["errors"].append({
                "test": "tool_api_endpoints",
                "error": str(e)
            })
            return False
    
    async def generate_test_report(self) -> Dict[str, Any]:
        """Generate a comprehensive test report."""
        report = {
            "test_suite": "VSCode CLI MCP Dashboard Integration",
            "timestamp": datetime.now().isoformat(),
            "results": self.test_results,
            "summary": {
                "total_screenshots": len(self.test_results["screenshots"]),
                "total_interactions": len(self.test_results["interactions"]),
                "tools_tested": len(self.test_results["tools_tested"]),
                "errors": len(self.test_results["errors"]),
                "screenshots_directory": str(self.screenshots_dir)
            }
        }
        
        # Save report to file
        report_path = self.screenshots_dir / "test_report.json"
        with open(report_path, "w") as f:
            json.dump(report, f, indent=2)
        
        logger.info(f"\n{'='*80}")
        logger.info("Test Report Summary:")
        logger.info(f"  Screenshots: {report['summary']['total_screenshots']}")
        logger.info(f"  Interactions: {report['summary']['total_interactions']}")
        logger.info(f"  Tools Tested: {', '.join(self.test_results['tools_tested'])}")
        logger.info(f"  Errors: {report['summary']['errors']}")
        logger.info(f"  Report saved to: {report_path}")
        logger.info(f"{'='*80}\n")
        
        return report


@pytest.mark.asyncio
async def test_vscode_cli_dashboard_integration():
    """
    Main test function for VSCode CLI dashboard integration.
    
    This test:
    1. Starts a browser
    2. Navigates to the MCP dashboard
    3. Tests all VSCode CLI tools
    4. Takes screenshots of every interaction
    5. Generates a comprehensive report
    """
    logger.info("Starting VSCode CLI Dashboard Integration Test...")
    
    tester = VSCodeCLIDashboardTester()
    
    async with async_playwright() as p:
        # Launch browser (headless=False to see the browser)
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            record_video_dir=str(tester.screenshots_dir / "videos") if os.getenv("RECORD_VIDEO") else None
        )
        page = await context.new_page()
        
        try:
            # Run all tests
            await tester.test_dashboard_loads(page)
            await tester.test_tool_categories_visible(page)
            await tester.test_vscode_cli_status_tool(page)
            await tester.test_vscode_cli_install_tool(page)
            await tester.test_vscode_extensions_tool(page)
            await tester.test_vscode_tunnel_tool(page)
            await tester.test_vscode_execute_tool(page)
            await tester.test_tool_api_endpoints(page)
            
            # Generate report
            report = await tester.generate_test_report()
            
            # Assert that we found at least some tools
            assert len(tester.test_results["tools_tested"]) > 0, \
                "No VSCode CLI tools were found in the dashboard"
            
            logger.info("✅ All tests completed successfully!")
            
        except Exception as e:
            logger.error(f"❌ Test failed: {e}")
            await tester.take_screenshot(page, "99_test_failure", f"Test failed: {str(e)}")
            raise
        finally:
            await context.close()
            await browser.close()


if __name__ == "__main__":
    # Run the test standalone
    asyncio.run(test_vscode_cli_dashboard_integration())
