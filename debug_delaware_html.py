#!/usr/bin/env python3
"""Debug Delaware HTML structure."""
import requests
from bs4 import BeautifulSoup

url = "https://delcode.delaware.gov/index.html"
print(f"Fetching: {url}\n")

response = requests.get(url, timeout=30)
print(f"Status: {response.status_code}")
print(f"Content-Length: {len(response.content)} bytes\n")

soup = BeautifulSoup(response.content, 'html.parser')

# Check for title-links divs
title_divs = soup.find_all('div', class_='title-links')
print(f"Found {len(title_divs)} div.title-links elements")

if title_divs:
    print("\nFirst title-links div content:")
    print("="*60)
    print(title_divs[0].prettify()[:500])
else:
    # Try finding any divs
    all_divs = soup.find_all('div')
    print(f"\nNo title-links divs found. Total divs: {len(all_divs)}")
    
    # Check for common class patterns
    classes = set()
    for div in all_divs:
        if div.get('class'):
            classes.update(div.get('class'))
    
    print(f"\nAll div classes found: {sorted(classes)[:20]}")
    
    # Check for any links with 'title' in them
    all_links = soup.find_all('a', href=True)
    title_links = [l for l in all_links if 'title' in l.get('href', '').lower() or 'title' in l.get_text().lower()]
    print(f"\nTotal links: {len(all_links)}")
    print(f"Links with 'title': {len(title_links)}")
    
    if title_links:
        print("\nFirst 5 title links:")
        for link in title_links[:5]:
            print(f"  - {link.get_text(strip=True)[:50]} -> {link.get('href')}")

# Show first 1000 chars of HTML
print("\n" + "="*60)
print("First 1000 chars of HTML:")
print("="*60)
print(response.text[:1000])
