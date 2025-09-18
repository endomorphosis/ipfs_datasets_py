#!/usr/bin/env python3
"""
Screenshot generator for the Deontic Logic Database dashboard
"""

import asyncio
import tempfile
import os
from pathlib import Path

try:
    from playwright.async_api import async_playwright
except ImportError:
    print("Playwright not available. Install with: pip install playwright")
    print("Then run: playwright install")
    exit(1)

async def create_deontic_dashboard_screenshot():
    """Create comprehensive screenshots of the deontic logic database dashboard"""
    
    # Get the HTML file path
    html_file = Path(__file__).parent / "deontic_logic_database_demo.html"
    
    if not html_file.exists():
        print(f"Error: {html_file} not found")
        return False
    
    async with async_playwright() as p:
        # Launch browser
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={'width': 1400, 'height': 1000})
        
        try:
            # Load the HTML file
            await page.goto(f"file://{html_file.absolute()}")
            
            # Wait for page to load
            await page.wait_for_timeout(2000)
            
            # Take main dashboard screenshot
            await page.screenshot(
                path="deontic_logic_database_dashboard.png",
                full_page=True,
                quality=90
            )
            print("✅ Created: deontic_logic_database_dashboard.png")
            
            # Screenshot of Logic Conversion tab (already active)
            conversion_section = page.locator('.demo-section')
            await conversion_section.screenshot(
                path="deontic_logic_conversion_demo.png",
                quality=90
            )
            print("✅ Created: deontic_logic_conversion_demo.png")
            
            # Click Search tab and screenshot
            await page.click('button:has-text("RAG Search")')
            await page.wait_for_timeout(500)
            await conversion_section.screenshot(
                path="deontic_rag_search_demo.png",
                quality=90
            )
            print("✅ Created: deontic_rag_search_demo.png")
            
            # Click Linting tab and screenshot
            await page.click('button:has-text("Conflict Linting")')
            await page.wait_for_timeout(500)
            await conversion_section.screenshot(
                path="deontic_conflict_linting_demo.png",
                quality=90
            )
            print("✅ Created: deontic_conflict_linting_demo.png")
            
            # Click Shepherding tab and screenshot
            await page.click('button:has-text("Case Shepherding")')
            await page.wait_for_timeout(500)
            await conversion_section.screenshot(
                path="deontic_case_shepherding_demo.png",
                quality=90
            )
            print("✅ Created: deontic_case_shepherding_demo.png")
            
            # Demonstrate functionality by clicking buttons
            
            # Go back to conversion tab and trigger demo
            await page.click('button:has-text("Logic Conversion")')
            await page.wait_for_timeout(500)
            await page.click('button:has-text("Convert to Deontic Logic")')
            await page.wait_for_timeout(1000)
            
            # Screenshot with results shown
            await conversion_section.screenshot(
                path="deontic_logic_conversion_results.png",
                quality=90
            )
            print("✅ Created: deontic_logic_conversion_results.png")
            
            # Go to search tab and trigger demo
            await page.click('button:has-text("RAG Search")')
            await page.wait_for_timeout(500)
            await page.click('button:has-text("Search Related Principles")')
            await page.wait_for_timeout(1000)
            
            await conversion_section.screenshot(
                path="deontic_rag_search_results.png",
                quality=90
            )
            print("✅ Created: deontic_rag_search_results.png")
            
            # Go to linting tab and trigger demo
            await page.click('button:has-text("Conflict Linting")')
            await page.wait_for_timeout(500)
            await page.click('button:has-text("Check for Conflicts")')
            await page.wait_for_timeout(1000)
            
            await conversion_section.screenshot(
                path="deontic_conflict_linting_results.png",
                quality=90
            )
            print("✅ Created: deontic_conflict_linting_results.png")
            
            # Go to shepherding tab and trigger demo
            await page.click('button:has-text("Case Shepherding")')
            await page.wait_for_timeout(500)
            await page.click('button:has-text("Validate Case Status")')
            await page.wait_for_timeout(1000)
            
            await conversion_section.screenshot(
                path="deontic_case_shepherding_results.png",
                quality=90
            )
            print("✅ Created: deontic_case_shepherding_results.png")
            
            return True
            
        except Exception as e:
            print(f"Error creating screenshots: {e}")
            return False
            
        finally:
            await browser.close()

def main():
    """Main function to create screenshots"""
    print("📸 Creating Deontic Logic Database Dashboard Screenshots")
    print("=" * 60)
    
    success = asyncio.run(create_deontic_dashboard_screenshot())
    
    if success:
        print("\n✅ All screenshots created successfully!")
        print("Screenshots saved in current directory:")
        print("  • deontic_logic_database_dashboard.png - Full dashboard view")
        print("  • deontic_logic_conversion_demo.png - Logic conversion interface")
        print("  • deontic_rag_search_demo.png - RAG search interface")
        print("  • deontic_conflict_linting_demo.png - Conflict linting interface")
        print("  • deontic_case_shepherding_demo.png - Case shepherding interface")
        print("  • deontic_logic_conversion_results.png - Conversion with results")
        print("  • deontic_rag_search_results.png - Search with results")
        print("  • deontic_conflict_linting_results.png - Linting with results")
        print("  • deontic_case_shepherding_results.png - Shepherding with results")
    else:
        print("\n❌ Failed to create screenshots")
        return 1
    
    return 0

if __name__ == "__main__":
    exit(main())