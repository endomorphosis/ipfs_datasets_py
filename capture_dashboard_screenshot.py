#!/usr/bin/env python3
"""Capture screenshots of the MCP dashboard."""

import anyio
from pathlib import Path
from playwright.async_api import async_playwright

async def capture_dashboard_screenshot():
    """Capture a full-page screenshot of the MCP dashboard."""
    
    dashboard_url = "http://127.0.0.1:8899/mcp"
    output_dir = Path("/tmp")
    
    async with async_playwright() as p:
        # Launch browser in headless mode
        browser = await p.chromium.launch(headless=True)
        
        # Create a new page with a large viewport
        page = await browser.new_page(viewport={"width": 1920, "height": 1080})
        
        try:
            # Navigate to the dashboard
            print(f"Navigating to {dashboard_url}...")
            await page.goto(dashboard_url, wait_until="networkidle", timeout=30000)
            
            # Wait for the main content to load
            await page.wait_for_selector("body", timeout=10000)
            
            # Give any dynamic content time to render
            await anyio.sleep(2)
            
            # Capture full-page screenshot
            full_screenshot_path = output_dir / "mcp_dashboard_full.png"
            await page.screenshot(path=str(full_screenshot_path), full_page=True)
            print(f"Full-page screenshot saved to: {full_screenshot_path}")
            
            # Capture viewport screenshot
            viewport_screenshot_path = output_dir / "mcp_dashboard_viewport.png"
            await page.screenshot(path=str(viewport_screenshot_path))
            print(f"Viewport screenshot saved to: {viewport_screenshot_path}")
            
            # Get page title and URL for verification
            title = await page.title()
            url = page.url
            print(f"Page title: {title}")
            print(f"Page URL: {url}")
            
        except Exception as e:
            print(f"Error capturing screenshot: {e}")
            raise
        finally:
            await browser.close()

if __name__ == "__main__":
    anyio.run(capture_dashboard_screenshot())
