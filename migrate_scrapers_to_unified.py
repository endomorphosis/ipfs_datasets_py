#!/usr/bin/env python3
"""
Legal Scraper Migration Tool

This script helps migrate existing legal scrapers to use the unified scraping architecture.
It audits existing scrapers and provides migration recommendations.
"""

import ast
import re
from pathlib import Path
from typing import Dict, List, Tuple
import json


class ScraperAuditor:
    """Audits scrapers to determine migration needs."""
    
    def __init__(self, root_dir: Path):
        self.root_dir = root_dir
        self.results = {
            "total_files": 0,
            "needs_migration": [],
            "already_migrated": [],
            "cannot_migrate": [],
            "scraping_patterns": {
                "beautifulsoup": [],
                "playwright": [],
                "requests": [],
                "aiohttp": [],
                "selenium": [],
                "unified_scraper": []
            }
        }
    
    def audit_file(self, file_path: Path) -> Dict:
        """Audit a single Python file."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            file_info = {
                "path": str(file_path),
                "uses_beautifulsoup": "BeautifulSoup" in content or "from bs4" in content,
                "uses_playwright": "playwright" in content.lower(),
                "uses_requests": "requests." in content or "import requests" in content,
                "uses_aiohttp": "aiohttp" in content,
                "uses_selenium": "selenium" in content,
                "uses_unified_scraper": "UnifiedWebScraper" in content or "unified_web_scraper" in content,
                "uses_base_scraper": "BaseLegalScraper" in content,
                "uses_content_addressed": "content_addressed_scraper" in content,
                "has_scrape_method": "def scrape(" in content or "async def scrape(" in content,
                "line_count": content.count('\n')
            }
            
            # Determine migration status
            if file_info["uses_base_scraper"] or file_info["uses_unified_scraper"]:
                file_info["status"] = "migrated"
            elif any([
                file_info["uses_beautifulsoup"],
                file_info["uses_playwright"],
                file_info["uses_requests"],
                file_info["uses_aiohttp"]
            ]):
                file_info["status"] = "needs_migration"
            else:
                file_info["status"] = "unknown"
            
            return file_info
            
        except Exception as e:
            return {
                "path": str(file_path),
                "status": "error",
                "error": str(e)
            }
    
    def audit_directory(self, directory: Path) -> None:
        """Audit all Python files in a directory."""
        for py_file in directory.rglob("*.py"):
            if "__pycache__" in str(py_file) or "__init__" in py_file.name:
                continue
            
            self.results["total_files"] += 1
            file_info = self.audit_file(py_file)
            
            if file_info["status"] == "migrated":
                self.results["already_migrated"].append(file_info)
            elif file_info["status"] == "needs_migration":
                self.results["needs_migration"].append(file_info)
            else:
                self.results["cannot_migrate"].append(file_info)
            
            # Track scraping patterns
            if file_info.get("uses_beautifulsoup"):
                self.results["scraping_patterns"]["beautifulsoup"].append(str(py_file))
            if file_info.get("uses_playwright"):
                self.results["scraping_patterns"]["playwright"].append(str(py_file))
            if file_info.get("uses_requests"):
                self.results["scraping_patterns"]["requests"].append(str(py_file))
            if file_info.get("uses_aiohttp"):
                self.results["scraping_patterns"]["aiohttp"].append(str(py_file))
            if file_info.get("uses_unified_scraper"):
                self.results["scraping_patterns"]["unified_scraper"].append(str(py_file))
    
    def print_report(self) -> None:
        """Print audit report."""
        print("\n" + "=" * 80)
        print("LEGAL SCRAPER MIGRATION AUDIT REPORT")
        print("=" * 80)
        
        print(f"\nTotal Python files audited: {self.results['total_files']}")
        print(f"Already migrated: {len(self.results['already_migrated'])}")
        print(f"Needs migration: {len(self.results['needs_migration'])}")
        print(f"Cannot migrate: {len(self.results['cannot_migrate'])}")
        
        print("\n" + "-" * 80)
        print("SCRAPING PATTERNS DETECTED")
        print("-" * 80)
        for pattern, files in self.results["scraping_patterns"].items():
            print(f"\n{pattern.upper()}: {len(files)} files")
            for file in files[:5]:  # Show first 5
                print(f"  - {file}")
            if len(files) > 5:
                print(f"  ... and {len(files) - 5} more")
        
        print("\n" + "-" * 80)
        print("FILES NEEDING MIGRATION")
        print("-" * 80)
        for file_info in self.results["needs_migration"][:10]:  # Show first 10
            print(f"\n{file_info['path']}")
            print(f"  Lines: {file_info.get('line_count', 'unknown')}")
            patterns = []
            if file_info.get("uses_beautifulsoup"):
                patterns.append("BeautifulSoup")
            if file_info.get("uses_playwright"):
                patterns.append("Playwright")
            if file_info.get("uses_requests"):
                patterns.append("requests")
            if file_info.get("uses_aiohttp"):
                patterns.append("aiohttp")
            print(f"  Uses: {', '.join(patterns)}")
        
        if len(self.results["needs_migration"]) > 10:
            print(f"\n  ... and {len(self.results['needs_migration']) - 10} more files")
    
    def save_report(self, output_file: Path) -> None:
        """Save audit report to JSON."""
        with open(output_file, 'w') as f:
            json.dump(self.results, f, indent=2)
        print(f"\nFull report saved to: {output_file}")


def main():
    """Main entry point."""
    root = Path("/home/devel/ipfs_datasets_py")
    
    print("Starting legal scraper audit...")
    print(f"Root directory: {root}")
    
    auditor = ScraperAuditor(root)
    
    # Audit key directories
    print("\nAuditing legal_dataset_tools...")
    legal_tools_dir = root / "ipfs_datasets_py/mcp_server/tools/legal_dataset_tools"
    if legal_tools_dir.exists():
        auditor.audit_directory(legal_tools_dir)
    
    print("\nAuditing legal_scrapers...")
    legal_scrapers_dir = root / "ipfs_datasets_py/legal_scrapers"
    if legal_scrapers_dir.exists():
        auditor.audit_directory(legal_scrapers_dir)
    
    # Print and save report
    auditor.print_report()
    auditor.save_report(root / "scraper_audit_report.json")
    
    print("\n" + "=" * 80)
    print("RECOMMENDATIONS")
    print("=" * 80)
    print("""
1. Priority 1: Migrate state scrapers (17 files using BeautifulSoup directly)
2. Priority 2: Migrate municipal database scrapers (municode, ecode360, american_legal)
3. Priority 3: Update MCP tools to use migrated scrapers
4. Priority 4: Add multiprocessing support for parallel scraping
5. Priority 5: Comprehensive testing

Next steps:
- Run: python migrate_state_scrapers.py
- Run: python migrate_municipal_scrapers.py
- Run: python test_unified_scraping_architecture.py
""")


if __name__ == "__main__":
    main()
