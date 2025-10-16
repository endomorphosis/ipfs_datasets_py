#!/usr/bin/env python3
"""
Diagnostic tool for analyzing failed state scrapers.

Usage:
    python3 analyze_failed_state.py AL  # Analyze Alabama
    python3 analyze_failed_state.py CT  # Analyze Connecticut
    python3 analyze_failed_state.py --all  # Analyze all failed states
"""

import sys
import asyncio
import argparse
from typing import Dict, Any
import requests
from bs4 import BeautifulSoup

# Add current directory to path
sys.path.insert(0, '.')

from state_scrapers import get_scraper_for_state, STATE_JURISDICTIONS


FAILED_STATES = ['AL', 'CT', 'DC', 'DE', 'GA', 'HI', 'IN', 'LA', 'MD', 'MO', 'RI', 'TN', 'WA', 'WY']


def analyze_http_response(state_code: str, url: str) -> Dict[str, Any]:
    """Analyze HTTP response from state website."""
    result = {
        'state_code': state_code,
        'url': url,
        'success': False,
        'status_code': None,
        'content_type': None,
        'content_length': 0,
        'has_links': False,
        'link_count': 0,
        'sample_links': [],
        'error': None
    }
    
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        response = requests.get(url, headers=headers, timeout=30, allow_redirects=True)
        result['status_code'] = response.status_code
        result['content_type'] = response.headers.get('Content-Type', 'Unknown')
        result['content_length'] = len(response.content)
        
        if response.status_code == 200:
            result['success'] = True
            
            # Parse HTML
            soup = BeautifulSoup(response.content, 'html.parser')
            links = soup.find_all('a', href=True)
            
            result['has_links'] = len(links) > 0
            result['link_count'] = len(links)
            result['sample_links'] = [
                {'text': link.get_text(strip=True)[:50], 'href': link['href'][:100]}
                for link in links[:10]
            ]
        else:
            result['error'] = f"HTTP {response.status_code}"
            
    except requests.exceptions.Timeout:
        result['error'] = "Request timeout (30s)"
    except requests.exceptions.ConnectionError as e:
        result['error'] = f"Connection error: {str(e)[:100]}"
    except Exception as e:
        result['error'] = f"Error: {type(e).__name__}: {str(e)[:100]}"
    
    return result


async def analyze_state_scraper(state_code: str) -> Dict[str, Any]:
    """Analyze a specific state scraper."""
    print(f"\n{'='*80}")
    print(f"Analyzing {state_code} - {STATE_JURISDICTIONS.get(state_code, 'Unknown')}")
    print(f"{'='*80}")
    
    # Get scraper
    try:
        scraper = get_scraper_for_state(state_code, STATE_JURISDICTIONS.get(state_code, 'Unknown'))
    except Exception as e:
        print(f"❌ Failed to get scraper: {e}")
        return {'state_code': state_code, 'error': str(e)}
    
    # Get base URL and codes
    base_url = scraper.get_base_url()
    codes = scraper.get_code_list()
    
    print(f"\n📍 Base URL: {base_url}")
    print(f"📚 Available Codes: {len(codes)}")
    
    if codes:
        print("\nCode List:")
        for i, code in enumerate(codes[:5], 1):
            print(f"  {i}. {code.get('name', 'N/A')}")
            print(f"     URL: {code.get('url', 'N/A')[:80]}")
    
    # Test first code URL
    if codes:
        test_url = codes[0]['url']
        print(f"\n🔍 Testing URL: {test_url}")
        
        http_result = analyze_http_response(state_code, test_url)
        
        print(f"\nHTTP Response Analysis:")
        print(f"  Status Code: {http_result['status_code']}")
        print(f"  Content Type: {http_result['content_type']}")
        print(f"  Content Length: {http_result['content_length']:,} bytes")
        print(f"  Has Links: {http_result['has_links']}")
        print(f"  Link Count: {http_result['link_count']}")
        
        if http_result['error']:
            print(f"  ❌ Error: {http_result['error']}")
        
        if http_result['sample_links']:
            print(f"\nSample Links (first 10):")
            for i, link in enumerate(http_result['sample_links'], 1):
                print(f"  {i}. {link['text']}")
                print(f"     → {link['href']}")
        
        # Try scraping
        print(f"\n🔧 Testing Scraper...")
        try:
            statutes = await scraper.scrape_code(codes[0]['name'], test_url)
            print(f"  ✅ Scraped {len(statutes)} statutes")
            
            if statutes:
                print(f"\nFirst Statute:")
                statute = statutes[0]
                print(f"  ID: {statute.statute_id}")
                print(f"  Code: {statute.code_name}")
                print(f"  Section: {statute.section_number}")
                print(f"  Name: {statute.section_name[:80]}")
                print(f"  Full Text: {statute.full_text[:80]}...")
                print(f"  Legal Area: {statute.legal_area}")
                print(f"  Citation: {statute.official_cite}")
            else:
                print(f"  ⚠️  No statutes returned (empty list)")
                
        except Exception as e:
            print(f"  ❌ Scraping failed: {type(e).__name__}: {str(e)[:100]}")
    
    return {
        'state_code': state_code,
        'base_url': base_url,
        'codes_count': len(codes),
        'http_status': http_result.get('status_code') if codes else None,
        'has_links': http_result.get('has_links') if codes else None,
        'link_count': http_result.get('link_count') if codes else None,
    }


async def analyze_all_failed_states():
    """Analyze all failed states."""
    print("\n" + "="*80)
    print("ANALYZING ALL FAILED STATES")
    print("="*80)
    
    results = []
    for state_code in FAILED_STATES:
        result = await analyze_state_scraper(state_code)
        results.append(result)
        await asyncio.sleep(2)  # Rate limiting
    
    # Summary
    print("\n" + "="*80)
    print("SUMMARY")
    print("="*80)
    
    for result in results:
        state = result['state_code']
        status = result.get('http_status', 'N/A')
        links = result.get('link_count', 0)
        print(f"{state}: HTTP {status}, {links} links found")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description='Analyze failed state scrapers')
    parser.add_argument('state_code', nargs='?', help='State code to analyze (e.g., AL, CT)')
    parser.add_argument('--all', action='store_true', help='Analyze all failed states')
    
    args = parser.parse_args()
    
    if args.all:
        asyncio.run(analyze_all_failed_states())
    elif args.state_code:
        state_code = args.state_code.upper()
        if state_code not in STATE_JURISDICTIONS:
            print(f"❌ Unknown state code: {state_code}")
            print(f"Valid codes: {', '.join(sorted(STATE_JURISDICTIONS.keys()))}")
            sys.exit(1)
        
        asyncio.run(analyze_state_scraper(state_code))
    else:
        print("Usage:")
        print("  python3 analyze_failed_state.py AL")
        print("  python3 analyze_failed_state.py --all")
        print(f"\nFailed states: {', '.join(FAILED_STATES)}")


if __name__ == '__main__':
    main()
