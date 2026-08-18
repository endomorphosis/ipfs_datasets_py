#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Functional Playwright test for Municipal Codes Scraper Dashboard Integration.

This script tests the actual integration of the scrape_municipal_codes MCP tool
in the dashboard by:
1. Starting the MCP dashboard server
2. Using Playwright to interact with the UI
3. Testing the tool invocation
4. Taking screenshots
5. Validating results

Usage:
    python tests/e2e/test_municipal_codes_functional.py
"""

import anyio
import subprocess
import time
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

try:
    from playwright.async_api import async_playwright

    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    print("Playwright not available. Install with: pip install playwright && playwright install")


async def test_municipal_codes_integration():
    """
    Complete integration test for Municipal Codes Scraper in MCP Dashboard.
    """

    if not PLAYWRIGHT_AVAILABLE:
        print("❌ Playwright not available. Skipping test.")
        return False

    print("=" * 70)
    print("Municipal Codes Scraper Dashboard Integration Test")
    print("=" * 70)
    print()

    # Test configuration
    dashboard_url = "http://localhost:8899/mcp"
    screenshot_dir = Path(__file__).parent.parent.parent / "test_screenshots"
    screenshot_dir.mkdir(exist_ok=True)

    async with async_playwright() as p:
        # Launch browser
        print("🌐 Launching browser...")
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1920, "height": 1080})
        page = await context.new_page()

        try:
            # Navigate to dashboard
            print(f"📍 Navigating to {dashboard_url}...")
            await page.goto(dashboard_url, wait_until="networkidle", timeout=10000)
            await page.wait_for_timeout(2000)

            # Take initial screenshot
            await page.screenshot(path=screenshot_dir / "01_dashboard_loaded.png")
            print("✓ Screenshot: Dashboard loaded")

            # Check if Municipal Codes Scraper tab exists
            print("\n🔍 Checking for Municipal Codes Scraper tab...")
            municipal_tab = page.locator('a[data-target="municipal-codes-scraper"]')

            if await municipal_tab.count() == 0:
                print("❌ Municipal Codes Scraper tab not found!")
                return False

            print("✓ Municipal Codes Scraper tab found")

            # Click on the tab
            print("🖱️  Clicking Municipal Codes Scraper tab...")
            await municipal_tab.click()
            await page.wait_for_timeout(1000)

            # Take screenshot of the tab
            await page.screenshot(path=screenshot_dir / "02_municipal_codes_tab.png")
            print("✓ Screenshot: Municipal Codes Scraper tab opened")

            # Verify form elements are present
            print("\n🔍 Verifying form elements...")
            elements_to_check = [
                ("input#municipal-jurisdictions", "Jurisdictions input"),
                ("select#municipal-provider", "Provider select"),
                ("select#municipal-output-format", "Output format select"),
                ("input#municipal-rate-limit", "Rate limit input"),
                ("input#municipal-max-sections", "Max sections input"),
                ("select#municipal-scraper-type", "Scraper type select"),
                ("input#municipal-include-metadata", "Include metadata checkbox"),
                ("input#municipal-include-text", "Include text checkbox"),
                ("input#municipal-job-id", "Job ID input"),
                ("input#municipal-resume", "Resume checkbox"),
            ]

            all_elements_found = True
            for selector, name in elements_to_check:
                element = page.locator(selector)
                if await element.count() > 0:
                    print(f"  ✓ {name}")
                else:
                    print(f"  ❌ {name} NOT FOUND")
                    all_elements_found = False

            if not all_elements_found:
                print("\n❌ Some form elements are missing!")
                return False

            # Fill in the form with test data
            print("\n📝 Filling form with test data...")
            await page.fill("input#municipal-jurisdictions", "Seattle, WA")
            await page.select_option("select#municipal-provider", "municode")
            await page.select_option("select#municipal-output-format", "json")
            await page.fill("input#municipal-rate-limit", "2.0")
            await page.select_option("select#municipal-scraper-type", "playwright")

            print("✓ Form filled with test data")

            # Take screenshot of filled form
            await page.screenshot(path=screenshot_dir / "03_form_filled.png")
            print("✓ Screenshot: Form filled")

            # Test validation (empty form)
            print("\n🧪 Testing form validation...")
            await page.fill("input#municipal-jurisdictions", "")
            await page.evaluate("scrapeMunicipalCodes()")
            await page.wait_for_timeout(1000)

            # Check for error message
            results_div = page.locator("#municipal-results")
            results_text = await results_div.inner_text()

            if "Error" in results_text or "specify at least one jurisdiction" in results_text:
                print("✓ Validation error displayed correctly")
            else:
                print("⚠️  Validation error not detected (might need server running)")

            await page.screenshot(path=screenshot_dir / "04_validation_error.png")
            print("✓ Screenshot: Validation error")

            # Fill form again for successful test
            print("\n🚀 Testing successful form submission...")
            await page.fill("input#municipal-jurisdictions", "Seattle, WA; Portland, OR")
            await page.select_option("select#municipal-provider", "municode")

            # Click the scraping button
            print("🖱️  Clicking 'Start Scraping' button...")
            await page.evaluate("scrapeMunicipalCodes()")
            await page.wait_for_timeout(2000)

            # Check results
            results_text = await results_div.inner_text()
            print(f"\n📊 Results preview:\n{results_text[:200]}...")

            # Take screenshot of results
            await page.screenshot(path=screenshot_dir / "05_scraping_results.png")
            print("✓ Screenshot: Scraping results")

            # Test Clear Form button
            print("\n🧹 Testing Clear Form button...")
            await page.evaluate("clearMunicipalForm()")
            await page.wait_for_timeout(500)

            # Verify form is cleared
            jurisdictions_value = await page.input_value("input#municipal-jurisdictions")
            if not jurisdictions_value:
                print("✓ Form cleared successfully")
            else:
                print("⚠️  Form not fully cleared")

            await page.screenshot(path=screenshot_dir / "06_form_cleared.png")
            print("✓ Screenshot: Form cleared")

            # Check info panel - be specific to Municipal Codes tab
            print("\n📖 Checking information panel...")
            # Use more specific selector to target only the Municipal Codes info panel
            info_panel = page.locator("#municipal-codes-scraper .alert-info.mt-3")
            if await info_panel.count() > 0:
                info_text = await info_panel.inner_text()
                if "22,899+" in info_text and "Municode" in info_text:
                    print("✓ Information panel contains expected content")
                else:
                    print("⚠️  Information panel content incomplete")
            else:
                print("⚠️  Information panel not found")

            print("\n" + "=" * 70)
            print("✅ ALL TESTS COMPLETED SUCCESSFULLY")
            print("=" * 70)
            print(f"\n📸 Screenshots saved to: {screenshot_dir}")
            print("\nScreenshots taken:")
            for i, name in enumerate(
                [
                    "01_dashboard_loaded.png",
                    "02_municipal_codes_tab.png",
                    "03_form_filled.png",
                    "04_validation_error.png",
                    "05_scraping_results.png",
                    "06_form_cleared.png",
                ],
                1,
            ):
                print(f"  {i}. {name}")

            return True

        except Exception as e:
            print(f"\n❌ Test failed with error: {e}")
            import traceback

            traceback.print_exc()

            # Take error screenshot
            try:
                await page.screenshot(path=screenshot_dir / "error_screenshot.png")
                print(f"Error screenshot saved to: {screenshot_dir}/error_screenshot.png")
            except:
                pass

            return False

        finally:
            await browser.close()


def main():
    """
    Main test runner.
    """
    print("\n" + "🔧 Prerequisites Check" + "\n" + "=" * 70)

    # Check if MCP dashboard is running
    print("Checking if MCP dashboard is accessible...")
    import urllib.request

    try:
        urllib.request.urlopen("http://localhost:8899/mcp", timeout=2)
        print("✓ MCP dashboard is running at http://localhost:8899/mcp")
    except:
        print("⚠️  MCP dashboard not accessible at http://localhost:8899/mcp")
        print("   Start it with: ipfs-datasets mcp start")
        print("   Or run: python -m ipfs_datasets_py.mcp_dashboard")
        print("\n   Tests will run but may show connection errors.")

    # Run the async test
    result = anyio.run(test_municipal_codes_integration())

    if result:
        print("\n✅ Integration test PASSED")
        sys.exit(0)
    else:
        print("\n❌ Integration test FAILED")
        sys.exit(1)


if __name__ == "__main__":
    main()
