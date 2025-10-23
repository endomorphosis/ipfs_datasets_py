#!/usr/bin/env python3
"""Inspect actual page content for Indiana and Tennessee."""
import asyncio
from playwright.async_api import async_playwright

async def inspect_page(url, state_name):
    """Inspect a page and show what's actually there."""
    print(f"\n{'='*60}")
    print(f"INSPECTING: {state_name}")
    print(f"URL: {url}")
    print('='*60)
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        try:
            print(f"\nLoading page...")
            await page.goto(url, wait_until='networkidle', timeout=60000)
            
            # Get all text content
            text_content = await page.evaluate('() => document.body.innerText')
            print(f"\nPage text (first 500 chars):")
            print(text_content[:500])
            
            # Get all links
            links = await page.evaluate('''() => {
                return Array.from(document.querySelectorAll('a')).map(a => ({
                    text: a.innerText.trim(),
                    href: a.href
                }));
            }''')
            
            print(f"\nTotal links found: {len(links)}")
            if links:
                print("\nFirst 10 links:")
                for i, link in enumerate(links[:10]):
                    print(f"  {i+1}. '{link['text'][:50]}' -> {link['href'][:80]}")
            
            # Try specific selectors
            print("\nTrying specific selectors:")
            
            for selector in ['div.content a', 'ul li a', 'table a', '[class*="title"] a', '[class*="code"] a']:
                try:
                    count = await page.locator(selector).count()
                    print(f"  {selector}: {count} elements")
                    if count > 0 and count < 20:
                        texts = await page.locator(selector).all_text_contents()
                        print(f"    Examples: {texts[:3]}")
                except:
                    pass
            
            # Get page structure
            print("\nPage structure:")
            structure = await page.evaluate('''() => {
                const divs = document.querySelectorAll('div[class], div[id]');
                const result = [];
                for (let i = 0; i < Math.min(divs.length, 10); i++) {
                    const div = divs[i];
                    result.push({
                        class: div.className,
                        id: div.id,
                        text: div.innerText.substring(0, 50)
                    });
                }
                return result;
            }''')
            
            for item in structure:
                if item['class'] or item['id']:
                    print(f"  div class='{item['class']}' id='{item['id']}' text='{item['text']}'")
            
        except Exception as e:
            print(f"\nError: {e}")
        finally:
            await browser.close()

async def main():
    """Inspect both states."""
    await inspect_page("https://iga.in.gov/legislative/laws/2024/ic/titles/", "Indiana")
    await inspect_page("https://www.tn.gov/tga/statutes.html", "Tennessee")

if __name__ == '__main__':
    asyncio.run(main())
