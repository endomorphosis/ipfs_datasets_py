#!/usr/bin/env python3
"""Check Indiana static documents page."""
import asyncio
from playwright.async_api import async_playwright

async def check_indiana():
    """Check what's at Indiana static documents."""
    url = "http://iga.in.gov/static-documents/"
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        try:
            print(f"Loading: {url}")
            await page.goto(url, wait_until='networkidle', timeout=60000)
            
            links = await page.evaluate('''() => {
                return Array.from(document.querySelectorAll('a')).map(a => ({
                    text: a.innerText.trim(),
                    href: a.href
                }));
            }''')
            
            print(f"\nTotal links: {len(links)}")
            
            # Filter for IC (Indiana Code) links
            ic_links = [l for l in links if 'ic' in l['text'].lower() or 'title' in l['text'].lower() or '.pdf' in l['href'].lower()]
            
            print(f"\nIC/Title/PDF links: {len(ic_links)}")
            for i, link in enumerate(ic_links[:15]):
                print(f"  {i+1}. {link['text'][:60]} -> {link['href'][:80]}")
            
        finally:
            await browser.close()

asyncio.run(check_indiana())
