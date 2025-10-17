#!/usr/bin/env python3
"""
Diagnostic test suite for failing state law scrapers.

This script tests the 11 failing states and provides detailed diagnostic
information that can be used to fix scraper issues. It also includes
fallback mechanisms using Internet Archive, Common Crawl, and other sources.

Run from VSCode desktop with network access:
    python diagnostic_test_states.py

The output will provide detailed information about:
- What URLs are being accessed
- What HTML structure is found
- What links are being filtered and why
- Suggestions for fixes based on the actual HTML
"""

import asyncio
import sys
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional
import traceback

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("ERROR: Missing required packages!")
    print("Install with: pip install requests beautifulsoup4")
    sys.exit(1)

from state_scrapers import (
    AlabamaScraper,
    ConnecticutScraper,
    DelawareScraper,
    GeorgiaScraper,
    HawaiiScraper,
    IndianaScraper,
    LouisianaScraper,
    MissouriScraper,
    SouthDakotaScraper,
    TennesseeScraper,
    WyomingScraper,
)


# Configure detailed logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('diagnostic_test.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)


class DiagnosticTester:
    """Diagnostic tester for state law scrapers."""
    
    def __init__(self, output_dir: str = "diagnostic_results"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        self.results = {}
        
    async def test_state(self, scraper, state_code: str, state_name: str) -> Dict[str, Any]:
        """Test a single state scraper with comprehensive diagnostics."""
        
        result = {
            "state_code": state_code,
            "state_name": state_name,
            "timestamp": datetime.now().isoformat(),
            "success": False,
            "diagnostics": {},
            "recommendations": [],
            "html_sample": None,
            "links_found": [],
            "links_accepted": [],
            "links_rejected": [],
            "errors": []
        }
        
        print(f"\n{'='*80}")
        print(f"TESTING: {state_name} ({state_code})")
        print(f"{'='*80}")
        
        try:
            # Get scraper info
            base_url = scraper.get_base_url()
            codes = scraper.get_code_list()
            
            result["base_url"] = base_url
            result["codes_available"] = len(codes)
            
            print(f"Base URL: {base_url}")
            print(f"Codes available: {len(codes)}")
            
            if not codes:
                result["errors"].append("No codes available")
                result["recommendations"].append("Check if get_code_list() is implemented correctly")
                return result
            
            code = codes[0]
            code_url = code['url']
            code_name = code['name']
            
            print(f"\nTesting code: {code_name}")
            print(f"URL: {code_url}")
            
            # Test 1: Check URL accessibility
            print(f"\n--- Test 1: URL Accessibility ---")
            url_test = await self._test_url_accessibility(code_url, state_code)
            result["diagnostics"]["url_accessibility"] = url_test
            
            if not url_test["accessible"]:
                # Try fallback methods
                print(f"\n--- Attempting Fallback Methods ---")
                fallback_result = await self._try_fallback_methods(code_url, state_code)
                result["diagnostics"]["fallback_methods"] = fallback_result
                
                if fallback_result["success"]:
                    print(f"✓ Fallback successful: {fallback_result['method']}")
                    code_url = fallback_result["url"]
                else:
                    result["errors"].append(f"URL not accessible: {url_test['error']}")
                    result["recommendations"].append("Check if URL is correct or if site is blocking access")
                    return result
            
            # Test 2: Fetch and analyze HTML
            print(f"\n--- Test 2: HTML Analysis ---")
            html_analysis = await self._analyze_html(code_url, state_code)
            result["diagnostics"]["html_analysis"] = html_analysis
            
            # Save HTML sample
            if html_analysis["html_content"]:
                html_file = self.output_dir / f"{state_code}_sample.html"
                with open(html_file, 'w', encoding='utf-8') as f:
                    f.write(html_analysis["html_content"][:50000])  # First 50KB
                result["html_sample"] = str(html_file)
                print(f"✓ HTML sample saved to: {html_file}")
            
            # Test 3: Analyze links
            print(f"\n--- Test 3: Link Analysis ---")
            link_analysis = await self._analyze_links(
                html_analysis["html_content"],
                state_code,
                scraper
            )
            result["diagnostics"]["link_analysis"] = link_analysis
            result["links_found"] = link_analysis["all_links"][:20]  # First 20
            result["links_accepted"] = link_analysis["accepted_links"][:20]
            result["links_rejected"] = link_analysis["rejected_links"][:20]
            
            print(f"\nLink Statistics:")
            print(f"  Total links found: {link_analysis['total_links']}")
            print(f"  Links with keywords: {link_analysis['links_with_keywords']}")
            print(f"  Links with numbers: {link_analysis['links_with_numbers']}")
            print(f"  Links accepted: {link_analysis['accepted_count']}")
            print(f"  Links rejected: {link_analysis['rejected_count']}")
            
            # Test 4: Try actual scraping
            print(f"\n--- Test 4: Scraper Execution ---")
            try:
                statutes = await scraper.scrape_code(code_name, code_url)
                result["statutes_scraped"] = len(statutes)
                result["success"] = len(statutes) > 0
                
                print(f"✓ Scraped {len(statutes)} statutes")
                
                if len(statutes) > 0:
                    print(f"\nSample statute:")
                    print(f"  ID: {statutes[0].statute_id}")
                    print(f"  Name: {statutes[0].section_name[:100]}")
                else:
                    result["errors"].append("Scraper returned 0 statutes")
                    
            except Exception as e:
                result["errors"].append(f"Scraper failed: {str(e)}")
                result["diagnostics"]["scraper_error"] = {
                    "type": type(e).__name__,
                    "message": str(e),
                    "traceback": traceback.format_exc()
                }
                print(f"✗ Scraper failed: {e}")
            
            # Generate recommendations
            result["recommendations"] = self._generate_recommendations(result, state_code)
            
        except Exception as e:
            result["errors"].append(f"Test failed: {str(e)}")
            result["diagnostics"]["test_error"] = traceback.format_exc()
            print(f"✗ Test failed: {e}")
        
        return result
    
    async def _test_url_accessibility(self, url: str, state_code: str) -> Dict[str, Any]:
        """Test if URL is accessible."""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            response = requests.get(url, headers=headers, timeout=30, allow_redirects=True)
            
            return {
                "accessible": response.status_code == 200,
                "status_code": response.status_code,
                "content_length": len(response.content),
                "content_type": response.headers.get('Content-Type', 'unknown'),
                "final_url": response.url,
                "redirected": response.url != url
            }
        except requests.exceptions.Timeout:
            return {"accessible": False, "error": "Timeout (30s)"}
        except requests.exceptions.RequestException as e:
            return {"accessible": False, "error": str(e)}
    
    async def _try_fallback_methods(self, url: str, state_code: str) -> Dict[str, Any]:
        """Try fallback methods to access content."""
        
        fallback_methods = []
        
        # Method 1: Internet Archive Wayback Machine
        try:
            wayback_url = f"http://archive.org/wayback/available?url={url}"
            response = requests.get(wayback_url, timeout=10)
            data = response.json()
            
            if data.get('archived_snapshots', {}).get('closest', {}).get('available'):
                archived_url = data['archived_snapshots']['closest']['url']
                fallback_methods.append({
                    "method": "Internet Archive",
                    "url": archived_url,
                    "timestamp": data['archived_snapshots']['closest'].get('timestamp'),
                    "success": True
                })
                return {"success": True, "method": "Internet Archive", "url": archived_url}
        except Exception as e:
            fallback_methods.append({
                "method": "Internet Archive",
                "success": False,
                "error": str(e)
            })
        
        # Method 2: Try HTTPS if HTTP
        if url.startswith('http://'):
            try:
                https_url = url.replace('http://', 'https://')
                response = requests.get(https_url, timeout=10)
                if response.status_code == 200:
                    fallback_methods.append({
                        "method": "HTTPS upgrade",
                        "url": https_url,
                        "success": True
                    })
                    return {"success": True, "method": "HTTPS upgrade", "url": https_url}
            except Exception as e:
                fallback_methods.append({
                    "method": "HTTPS upgrade",
                    "success": False,
                    "error": str(e)
                })
        
        # Method 3: Try HTTP if HTTPS
        if url.startswith('https://'):
            try:
                http_url = url.replace('https://', 'http://')
                response = requests.get(http_url, timeout=10)
                if response.status_code == 200:
                    fallback_methods.append({
                        "method": "HTTP downgrade",
                        "url": http_url,
                        "success": True
                    })
                    return {"success": True, "method": "HTTP downgrade", "url": http_url}
            except Exception as e:
                fallback_methods.append({
                    "method": "HTTP downgrade",
                    "success": False,
                    "error": str(e)
                })
        
        return {
            "success": False,
            "methods_tried": fallback_methods
        }
    
    async def _analyze_html(self, url: str, state_code: str) -> Dict[str, Any]:
        """Analyze HTML structure of the page."""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Analyze structure
            return {
                "html_content": response.text,
                "total_links": len(soup.find_all('a')),
                "has_tables": len(soup.find_all('table')) > 0,
                "has_lists": len(soup.find_all(['ul', 'ol'])) > 0,
                "has_divs": len(soup.find_all('div')) > 0,
                "title": soup.title.string if soup.title else None,
                "encoding": response.encoding,
                "uses_javascript": bool(soup.find_all('script'))
            }
        except Exception as e:
            return {
                "error": str(e),
                "html_content": None
            }
    
    async def _analyze_links(self, html_content: str, state_code: str, scraper) -> Dict[str, Any]:
        """Analyze links found on the page."""
        if not html_content:
            return {
                "error": "No HTML content available",
                "total_links": 0,
                "accepted_count": 0,
                "rejected_count": 0,
                "all_links": [],
                "accepted_links": [],
                "rejected_links": []
            }
        
        soup = BeautifulSoup(html_content, 'html.parser')
        links = soup.find_all('a', href=True)
        
        # Keywords to look for (comprehensive list)
        statute_keywords = [
            'title', 'chapter', '§', 'section', 'sec.', 'part', 
            'code', 'statute', 'article', 'division', 'vol', 'volume',
            'act', 'law', 'revised', 'annotated', 'general'
        ]
        
        all_links = []
        accepted_links = []
        rejected_links = []
        links_with_keywords = 0
        links_with_numbers = 0
        
        for link in links[:200]:  # Analyze first 200 links
            link_text = link.get_text(strip=True)
            link_href = link.get('href', '')
            
            if not link_text:
                continue
            
            link_info = {
                "text": link_text[:100],
                "href": link_href[:100],
                "length": len(link_text)
            }
            
            # Check characteristics
            has_keywords = any(kw in link_text.lower() for kw in statute_keywords)
            has_numbers = any(c.isdigit() for c in link_text)
            
            if has_keywords:
                links_with_keywords += 1
                link_info["has_keywords"] = True
            
            if has_numbers:
                links_with_numbers += 1
                link_info["has_numbers"] = True
            
            all_links.append(link_info)
            
            # Determine if would be accepted (simplified logic)
            if len(link_text) >= 5 and (has_keywords or has_numbers):
                accepted_links.append(link_info)
            else:
                link_info["reject_reason"] = "too_short" if len(link_text) < 5 else "no_keywords_or_numbers"
                rejected_links.append(link_info)
        
        return {
            "total_links": len(links),
            "links_with_keywords": links_with_keywords,
            "links_with_numbers": links_with_numbers,
            "accepted_count": len(accepted_links),
            "rejected_count": len(rejected_links),
            "all_links": all_links,
            "accepted_links": accepted_links,
            "rejected_links": rejected_links
        }
    
    def _generate_recommendations(self, result: Dict[str, Any], state_code: str) -> List[str]:
        """Generate recommendations based on test results."""
        recommendations = []
        
        # Check URL accessibility
        if not result["diagnostics"].get("url_accessibility", {}).get("accessible"):
            recommendations.append("⚠️  URL not accessible - Check if site is online or blocking automated access")
            recommendations.append("💡 Try accessing URL in browser manually to verify")
            recommendations.append("💡 Consider using Internet Archive or other fallback sources")
        
        # Check HTML structure
        html_analysis = result["diagnostics"].get("html_analysis", {})
        if html_analysis.get("uses_javascript"):
            recommendations.append("⚠️  Page uses JavaScript - May need Playwright for rendering")
            recommendations.append("💡 Install Playwright: pip install playwright && playwright install chromium")
        
        # Check link analysis
        link_analysis = result["diagnostics"].get("link_analysis", {})
        if link_analysis:
            total = link_analysis.get("total_links", 0)
            accepted = link_analysis.get("accepted_count", 0)
            
            if total > 0 and accepted == 0:
                recommendations.append("⚠️  Found links but none matched filtering criteria")
                recommendations.append("💡 Review link samples in diagnostic output")
                recommendations.append("💡 May need to adjust keyword matching or add state-specific patterns")
            
            if total == 0:
                recommendations.append("⚠️  No links found on page")
                recommendations.append("💡 Page may use JavaScript to load content")
                recommendations.append("💡 Check HTML sample to verify structure")
        
        # Check scraper errors
        if result.get("errors"):
            for error in result["errors"]:
                if "timeout" in error.lower():
                    recommendations.append("💡 Increase timeout value for slow connections")
                if "403" in error or "forbidden" in error.lower():
                    recommendations.append("💡 Site may be blocking automated access - try different User-Agent")
                if "404" in error or "not found" in error.lower():
                    recommendations.append("💡 URL may have changed - check state's legislative website")
        
        return recommendations
    
    async def run_all_tests(self):
        """Run tests for all failing states."""
        
        failing_states = [
            (AlabamaScraper("AL", "Alabama"), "AL", "Alabama"),
            (ConnecticutScraper("CT", "Connecticut"), "CT", "Connecticut"),
            (DelawareScraper("DE", "Delaware"), "DE", "Delaware"),
            (GeorgiaScraper("GA", "Georgia"), "GA", "Georgia"),
            (HawaiiScraper("HI", "Hawaii"), "HI", "Hawaii"),
            (IndianaScraper("IN", "Indiana"), "IN", "Indiana"),
            (LouisianaScraper("LA", "Louisiana"), "LA", "Louisiana"),
            (MissouriScraper("MO", "Missouri"), "MO", "Missouri"),
            (SouthDakotaScraper("SD", "South Dakota"), "SD", "South Dakota"),
            (TennesseeScraper("TN", "Tennessee"), "TN", "Tennessee"),
            (WyomingScraper("WY", "Wyoming"), "WY", "Wyoming"),
        ]
        
        print("\n" + "="*80)
        print("DIAGNOSTIC TEST SUITE FOR FAILING STATE LAW SCRAPERS")
        print("="*80)
        print(f"\nTesting {len(failing_states)} states")
        print(f"Output directory: {self.output_dir}")
        print(f"Log file: diagnostic_test.log")
        
        for scraper, state_code, state_name in failing_states:
            result = await self.test_state(scraper, state_code, state_name)
            self.results[state_code] = result
            
            # Save individual result
            result_file = self.output_dir / f"{state_code}_diagnostic.json"
            with open(result_file, 'w') as f:
                json.dump(result, f, indent=2, default=str)
            print(f"\n✓ Diagnostic report saved: {result_file}")
        
        # Generate summary report
        self._generate_summary()
    
    def _generate_summary(self):
        """Generate summary report."""
        summary_file = self.output_dir / "diagnostic_summary.json"
        
        summary = {
            "timestamp": datetime.now().isoformat(),
            "total_states": len(self.results),
            "successful": sum(1 for r in self.results.values() if r.get("success")),
            "failed": sum(1 for r in self.results.values() if not r.get("success")),
            "states": {}
        }
        
        print("\n" + "="*80)
        print("DIAGNOSTIC SUMMARY")
        print("="*80)
        
        for state_code, result in sorted(self.results.items()):
            status = "✓ SUCCESS" if result.get("success") else "✗ FAILED"
            statutes = result.get("statutes_scraped", 0)
            
            print(f"\n{state_code} ({result['state_name']}): {status}")
            print(f"  Statutes scraped: {statutes}")
            
            if result.get("errors"):
                print(f"  Errors: {len(result['errors'])}")
                for error in result['errors'][:3]:
                    print(f"    - {error}")
            
            if result.get("recommendations"):
                print(f"  Recommendations: {len(result['recommendations'])}")
                for rec in result['recommendations'][:3]:
                    print(f"    {rec}")
            
            summary["states"][state_code] = {
                "success": result.get("success"),
                "statutes": statutes,
                "errors": len(result.get("errors", [])),
                "recommendations": len(result.get("recommendations", []))
            }
        
        with open(summary_file, 'w') as f:
            json.dump(summary, f, indent=2)
        
        print(f"\n{'='*80}")
        print(f"Summary saved to: {summary_file}")
        print(f"Individual diagnostics in: {self.output_dir}/")
        print(f"Full log in: diagnostic_test.log")
        print(f"{'='*80}")


async def main():
    """Main entry point."""
    tester = DiagnosticTester()
    await tester.run_all_tests()


if __name__ == "__main__":
    asyncio.run(main())
